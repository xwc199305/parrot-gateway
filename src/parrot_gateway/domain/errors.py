from typing import Any


class ProviderError(Exception):
    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail))


class BillingError(Exception):
    """A request cannot be admitted because billing policy rejected it."""

    def __init__(self, message: str, status_code: int = 402) -> None:
        self.status_code = status_code
        self.detail = {"error": {"type": "billing_error", "message": message}}
        super().__init__(message)
