"""真实大模型策略适配器（OpenAI 兼容接口）。

- 默认不启用；CLI 默认 mock 策略，保证离线可复现。
- 默认使用内置零依赖 HTTP 客户端（支持 DeepSeek 等 OpenAI 兼容接口）；
  也可以通过参数注入自定义 client（测试用 fake client）。
- 动作协议与 MockPolicy 一致；模型异常/非法输出统一转 PolicyError。
"""

import json
import os
from typing import Any, Dict, Optional

from ..errors import PolicyError
from ..schemas import Action

SYSTEM_PROMPT = """你是素材审核与发布排期 Agent 的决策器。每轮只输出一个 JSON 对象，不要输出解释：
{"action": "<动作>", "args": {...}, "decision_basis": "一句话说明"}

可用动作与参数：
- get_material: {"material_id": "..."}
- check_rules: {"material_id": "..."}
- query_slots: {"date": "YYYY-MM-DD", "requested_time": "HH:MM"}
- save_draft: {"date": "...", "time": "...", "requested_time": "...", "hard": true/false}
- finish: {"status": "...", "review_status": "...", "reason": "...", "pending": [...]}

必须遵守的顺序约束：
1. 未读取素材前只能 get_material；
2. 未做规则检查前不能 query_slots 或 save_draft；
3. 存在 high 风险时必须 finish(BLOCKED, RISK_BLOCKED)，禁止查询时段或保存；
4. 未查询时段前不能 save_draft；
5. save_draft 的 date/time 必须等于 state.proposed 的 date/time；requested_time 与 hard 必须等于 request 中的值，不得改写；
6. 只允许保存草稿，禁止发布；
7. 工具报错（save_error/tool_error）必须如实结束为 SAVE_FAILED 或 ERROR，不得声称成功；
8. 可选状态：NEEDS_CONFIRMATION / NEEDS_INPUT / BLOCKED / SAVE_FAILED / INCOMPLETE / ERROR；
   NEEDS_CONFIRMATION 必须已有 draft_result.saved=true；PASS 必须已完成规则检查且无 high 风险。

请根据 state 选择下一步，只输出 JSON。

额外硬约束：
- `state.allowed_actions` 是当前唯一允许的动作集合，必须从中选择；
- 若 `state.progress` 显示某步骤已完成，禁止重复调用（如 rules_checked=true 时不得再 check_rules）；
- 只能调用一次 get_material；draft_saved=true 时只能 finish。"""


class OpenAIPolicy:
    name = "openai-policy"

    def __init__(self, model: Optional[str] = None, client=None,
                 base_url: Optional[str] = None, api_key: Optional[str] = None):
        self.model = model or os.environ.get("OPENAI_MODEL") or "deepseek-chat"
        self._client = client
        self._base_url = base_url
        self._api_key = api_key

    def _client_or_raise(self):
        if self._client is not None:
            return self._client
        api_key = self._api_key or os.environ.get("OPENAI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise PolicyError("MODEL_NOT_CONFIGURED", "未配置 OPENAI_API_KEY / DEEPSEEK_API_KEY，真实模型不可用")
        base_url = (self._base_url or os.environ.get("OPENAI_BASE_URL")
                    or os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com/v1")
        from .http_client import LLMHttpClient

        self._client = LLMHttpClient(base_url=base_url, api_key=api_key)
        return self._client

    def decide(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        client = self._client_or_raise()
        request = ctx["request"]
        material = ctx.get("material")
        risks = ctx.get("risks")
        high_risk = any(r.get("severity") == "high" for r in (risks or []))
        draft = ctx.get("draft_result") or {}
        progress = {
            "material_read": material is not None,
            "rules_checked": risks is not None,
            "high_risk": high_risk,
            "slot_checked": ctx.get("slot_info") is not None,
            "proposed": ctx.get("proposed"),
            "draft_saved": bool(draft.get("saved")),
            "save_error": ctx.get("save_error"),
            "tool_error": ctx.get("tool_error"),
        }
        state = {
            "request": {
                "material_id": request.material_id,
                "publish_date": request.publish_date,
                "publish_time": request.publish_time,
                "hard": request.hard,
            },
            "material": material,
            "risks": risks,
            "slot_info": ctx.get("slot_info"),
            "proposed": ctx.get("proposed"),
            "draft_result": ctx.get("draft_result"),
            "save_error": ctx.get("save_error"),
            "tool_error": ctx.get("tool_error"),
            "progress": progress,
            "allowed_actions": self._allowed_actions(ctx, high_risk),
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

    @staticmethod
    def _allowed_actions(ctx: Dict[str, Any], high_risk: bool) -> list:
        request = ctx["request"]
        if request.validation_errors:
            return ["finish"]
        material = ctx.get("material")
        if material is None and ctx.get("material_error") is None:
            return ["get_material"]
        if ctx.get("material_error") or (material and material.get("missing_fields")):
            return ["finish"]
        if ctx.get("risks") is None:
            return ["check_rules", "finish"]
        if high_risk:
            return ["finish"]
        if ctx.get("slot_info") is None:
            return ["query_slots", "finish"]
        draft = ctx.get("draft_result") or {}
        if draft.get("saved"):
            return ["finish"]
        if ctx.get("save_error"):
            return ["query_slots", "finish"]
        if ctx.get("proposed"):
            return ["save_draft", "finish"]
        return ["query_slots", "finish"]
