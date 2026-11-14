"""业务异常，统一转换为 HTTP 响应。"""
from typing import Any


class BizError(Exception):
    def __init__(self, status_code: int, message: str, detail: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.detail = detail
