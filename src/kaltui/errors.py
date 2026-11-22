"""Safe, user-facing errors; never expose HTTP bodies or credential material."""


class KaltuiError(Exception):
    pass


class APIError(KaltuiError):
    def __init__(self, message: str, retry_after: float = 0):
        super().__init__(message)
        self.retry_after = retry_after
