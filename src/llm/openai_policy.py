"""可选：真实大模型策略适配器（OpenAI 兼容接口）。

边界说明：
- 默认不使用；CLI 只暴露 mock 策略，评测与测试均基于 MockPolicy。
- 本适配器未被自动化测试覆盖（需要真实 API Key），仅作为接入示意。
- 动作协议与 MockPolicy 完全一致：返回 {"action", "args", "decision_basis"}。
"""

import json
import os
from typing import Any, Dict

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
            raise RuntimeError("未配置 OPENAI_API_KEY，真实模型不可用；请改用 --policy mock")
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
        resp = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(state, ensure_ascii=False)},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content)
        return {
            "action": data["action"],
            "args": data.get("args", {}),
            "decision_basis": data.get("decision_basis", ""),
        }
