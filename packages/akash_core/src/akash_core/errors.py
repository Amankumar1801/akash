class AkashError(Exception):
    """Base class for all AKASH errors."""


class ValidationFailure(AkashError):
    """Data failed a validation rule (quarantine, don't silently drop)."""


class ProviderError(AkashError):
    """An external data provider failed."""


class AmbiguousIdentity(AkashError):
    """An identifier resolved to multiple plausible objects."""

    def __init__(self, message: str, candidates: list[str] | None = None) -> None:
        super().__init__(message)
        self.candidates = candidates or []
