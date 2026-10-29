"""零依赖的 OpenAI 兼容 HTTP 客户端。

用途：在不安装 openai SDK 的情况下调用 OpenAI 兼容接口（如 DeepSeek）。
只实现本项目用到的 `chat.completions.create` 子集，返回值结构与 openai SDK 一致。

注意：显式禁用系统代理（ProxyHandler({})），避免 Windows 注册表代理干扰；
在没有代理的环境下直连 API。
"""

import json
import urllib.error
import urllib.request
from types import SimpleNamespace
from typing import Any, Dict, List, Optional


class _Completions:
    def __init__(self, base_url: str, api_key: str, timeout: float):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.api_key = api_key
        self.timeout = timeout

    def create(self, model: str, messages: List[Dict[str, Any]],
               temperature: float = 0, response_format: Optional[Dict[str, Any]] = None,
               **kwargs) -> Any:
        payload: Dict[str, Any] = {"model": model, "messages": messages, "temperature": temperature}
        if response_format:
            payload["response_format"] = response_format
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"HTTP {exc.code}: {detail}")
        except urllib.error.URLError as exc:
            raise RuntimeError(f"网络错误: {exc.reason}")
        data = json.loads(body)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"响应结构异常: {exc}")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


class LLMHttpClient:
    """与 openai.OpenAI 相同的最小接口：client.chat.completions.create(...)"""

    def __init__(self, base_url: str, api_key: str, timeout: float = 120.0):
        self.chat = SimpleNamespace(completions=_Completions(base_url, api_key, timeout))
