"""Tests for retryable/non-retryable error classification."""

import pytest

from ingestion_worker.errors import (
    NonRetryableIngestionError,
    RetryableIngestionError,
    classify_exception,
    is_retryable,
)


class _ProviderError(Exception):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


@pytest.mark.parametrize("status", [408, 425, 429, 500, 502, 503, 504])
def test_retryable_http_statuses(status):
    assert is_retryable(_ProviderError("provider", status_code=status)) is True


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_non_retryable_http_statuses(status):
    assert is_retryable(_ProviderError("provider", status_code=status)) is False


def test_timeout_messages_are_retryable():
    assert is_retryable(RuntimeError("connection timeout while calling provider"))


def test_plain_validation_error_is_not_retryable():
    assert is_retryable(ValueError("could not parse file")) is False


def test_classify_wraps_into_the_matching_error():
    assert isinstance(
        classify_exception(_ProviderError("rate limit", status_code=429)),
        RetryableIngestionError,
    )
    assert isinstance(
        classify_exception(ValueError("bad input")),
        NonRetryableIngestionError,
    )


def test_classify_passes_through_already_classified_errors():
    original = RetryableIngestionError("boom")
    assert classify_exception(original) is original