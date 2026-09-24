"""Error classification for ingestion tasks.

The retry layer belongs in the Celery task wrapper, not in `common`'s pure
provider call (ADR-0005, "LLM / Provider Rate Limits"). External providers are
retryable on 429/5xx and non-retryable on 4xx validation errors; malformed input
is non-retryable. This module turns an arbitrary exception into one of the two
classified errors the task uses to decide whether to retry.
"""

RETRYABLE_HTTP_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

_RETRYABLE_MARKERS = (
    "rate limit",
    "ratelimit",
    "timeout",
    "timed out",
    "temporarily",
    "too many requests",
    "connection reset",
    "service unavailable",
)


class IngestionError(Exception):
    """Base class for classified ingestion failures."""


class RetryableIngestionError(IngestionError):
    """A transient failure; the task should retry with backoff."""


class NonRetryableIngestionError(IngestionError):
    """A permanent failure; the task should not be retried."""


def _status_code(exc: Exception) -> int | None:
    for attribute in ("status_code", "http_status", "code"):
        value = getattr(exc, attribute, None)
        if isinstance(value, int):
            return value
    return None


def is_retryable(exc: Exception) -> bool:
    """Classify an exception as retryable (True) or permanent (False)."""
    status = _status_code(exc)
    if status is not None:
        return status in RETRYABLE_HTTP_STATUS
    text = str(exc).lower()
    return any(marker in text for marker in _RETRYABLE_MARKERS)


def classify_exception(exc: Exception) -> IngestionError:
    """Wrap an exception in the matching classified `IngestionError`."""
    if isinstance(exc, IngestionError):
        return exc
    if is_retryable(exc):
        return RetryableIngestionError(str(exc))
    return NonRetryableIngestionError(str(exc))


__all__ = [
    "IngestionError",
    "RetryableIngestionError",
    "NonRetryableIngestionError",
    "is_retryable",
    "classify_exception",
]