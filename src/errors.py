"""工具层错误定义。工具失败必须显式向上抛出，禁止静默吞掉。"""


class ToolError(Exception):
    """任何工具调用失败都使用该异常，带机器可读的 code。"""

    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}
