import re


class ProviderError(Exception):
    pass

class ProviderPayloadTooLargeError(ProviderError):
    def __init__(self, message: str, requested_tokens: int | None = None, limit_tokens: int | None = None, status_code: int = 413):
        super().__init__(message)
        self.requested_tokens = requested_tokens
        self.limit_tokens = limit_tokens
        self.status_code = status_code

class ProviderRateLimitError(ProviderError):
    def __init__(self, message: str, retry_after: float | None = None, status_code: int = 429):
        super().__init__(message)
        self.retry_after = retry_after
        self.status_code = status_code

class RequestBudgetExceededError(ProviderError):
    def __init__(self, message: str, estimated_tokens: int, budget_limit: int, breakdown: dict | None = None):
        super().__init__(message)
        self.estimated_tokens = estimated_tokens
        self.budget_limit = budget_limit
        self.breakdown = breakdown or {}

def classify_provider_exception(exc: Exception) -> Exception:
    if isinstance(exc, (ProviderPayloadTooLargeError, ProviderRateLimitError, RequestBudgetExceededError)):
        return exc
    
    raw_status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    try:
        status = int(raw_status) if raw_status is not None else None
    except (TypeError, ValueError):
        status = None
    msg = str(exc).lower()
    
    is_413 = status == 413 or any(k in msg for k in ["payload too large", "request too large", "context_length_exceeded", "maximum context length", "tpm", "413"])
    if is_413:
        req, lim = None, None
        m_req = re.search(r"requested[:\s]*(\d+)", msg)
        if m_req:
            req = int(m_req.group(1))
        m_lim = re.search(r"limit[:\s]*(\d+)", msg)
        if m_lim:
            lim = int(m_lim.group(1))
        return ProviderPayloadTooLargeError(str(exc), requested_tokens=req, limit_tokens=lim)
    
    if status == 429 or "rate limit" in msg:
        return ProviderRateLimitError(str(exc))
        
    return exc
