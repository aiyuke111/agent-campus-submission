"""可选：真实大模型策略适配器（OpenAI 兼容接口）。

边界说明：
- 默认不使用；CLI 默认 mock 策略，保证离线可复现。
- 本适配器通过注入 client 可做单元测试（不需要真实 Key），真实网络调用未在评测中执行。
- 动作协议与 MockPolicy 一致：返回 {"action", "args", "decision_basis"}；
  任何模型异常（网络、空响应、非 JSON、字段缺失）都转成 PolicyError。
"""

import json
import os
from typing import Any, Dict, Optional

from ..errors import PolicyError
from ..schemas import Action

SYSTEM_PROMPT = """你是素材审核与发布排期 Agent 的决策器。
只能输出如下 JSON，不要输出其它文本：
{"action": "<get_material|check_rules|query_slots|save_draft|finish>",
 "args": {...},
 "decision_basis": "一句话说明为什么这样决策"}

规则：
1. 只允许保存草稿，禁止发布；
2. 用户的硬性发布时间不得擅自修改，若冲突只能提出替代时段并标记待确认；
3. 工具失败时必须如实返回失败，不得声称成功。"""


class OpenAIPolicy:
    name = "openai-policy"

    def __init__(self, model: str = "gpt-4o-mini", client=None):
        self.model = model
        self._client = client

    def _client_or_raise(self):
        if self._client is not None:
            return self._client
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise PolicyError("MODEL_NOT_CONFIGURED", "未配置 OPENAI_API_KEY，真实模型不可用")
        from openai import OpenAI  # 可选依赖，仅真实模式需要

        self._client = OpenAI(api_key=api_key)
        return self._client

    def decide(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        client = self._client_or_raise()
        request = ctx["request"]
        state = {
            "request": {
                "material_id": request.material_id,
                "publish_date": request.publish_date,
                "publish_time": request.publish_time,
                "hard": request.hard,
            },
            "material": ctx.get("material"),
            "risks": ctx.get("risks"),
            "slot_info": ctx.get("slot_info"),
            "proposed": ctx.get("proposed"),
            "draft_result": ctx.get("draft_result"),
            "save_error": ctx.get("save_error"),
            "tool_error": ctx.get("tool_error"),
        }
        try:
            resp = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(state, ensure_ascii=False)},
                ],
                temperature=0,
                response_format={"type": "json_object"},
            )
        except Exception as exc:  # noqa: BLE001 - 网络/鉴权等异常统一转 PolicyError
            raise PolicyError("MODEL_CALL_FAILED", f"模型调用失败: {exc}")

        try:
            content = resp.choices[0].message.content
        except (AttributeError, IndexError, TypeError) as exc:
            raise PolicyError("MODEL_RESPONSE_INVALID", f"模型响应结构异常: {exc}")
        if not content or not isinstance(content, str):
            raise PolicyError("MODEL_RESPONSE_INVALID", "模型返回内容为空")

        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise PolicyError("MODEL_BAD_JSON", f"模型返回不是合法 JSON: {exc}")

        if not isinstance(data, dict):
            raise PolicyError("MODEL_BAD_JSON", "模型返回不是 JSON 对象")
        action = data.get("action")
        if action not in Action.TOOLS and action != Action.FINISH:
            raise PolicyError("MODEL_BAD_ACTION", f"模型返回了未知动作: {action}")
        args = data.get("args", {})
        if not isinstance(args, dict):
            raise PolicyError("MODEL_BAD_JSON", "模型返回的 args 不是对象")

        return {
            "action": action,
            "args": args,
            "decision_basis": str(data.get("decision_basis", "")),
        }
