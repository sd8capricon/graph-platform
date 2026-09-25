"""Provider-agnostic object storage abstraction.

Business logic depends on `StorageService` only - never on the Azure SDK or on
filesystem APIs - and refers to stored objects by **object key**, a
provider-independent, `/`-separated name such as
`documents/{documentId}/{fileId}/content.pdf`. A key is the canonical storage
reference: persist keys, never a physical filesystem path or a blob URL, so the
provider can change without rewriting stored references.
"""

import re
from abc import ABC, abstractmethod
from collections.abc import AsyncIterable, AsyncIterator, Mapping
from datetime import datetime
from types import TracebackType
from typing import Self

from pydantic import BaseModel, ConfigDict, Field

MAX_KEY_LENGTH = 1024
"""Longest accepted object key, in characters (Azure Blob's blob-name limit)."""

DEFAULT_CHUNK_SIZE = 1024 * 1024
"""Default size in bytes of each chunk `StorageService.download()` yields."""

_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")
_METADATA_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class StorageError(Exception):
    """Base class for every error raised by a `StorageService`.

    Provider SDK errors are wrapped in this type so callers never need to import
    a provider's exception classes.

    Attributes:
        status_code: The provider's HTTP status code, when there was one. Kept so
            retry classification (e.g. the ingestion worker's
            `classify_exception()`, which reads `status_code`) still works.
    """

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class StorageObjectNotFoundError(StorageError):
    """Raised when an operation needs an object that does not exist.

    Attributes:
        key: The object key that was not found.
    """

    def __init__(self, key: str):
        super().__init__(f"storage object not found: {key!r}")
        self.key = key


class InvalidStorageKeyError(StorageError, ValueError):
    """Raised when an object key, list prefix, or metadata entry is invalid.

    Also a `ValueError`, the codebase's convention for rejected input.
    """


class ObjectMetadata(BaseModel):
    """Provider-independent description of one stored object.

    Never carries a physical path or URL - only the object key.

    Attributes:
        key: The object key.
        size: Content length in bytes.
        content_type: MIME type recorded at upload, or `None` if none was given.
        etag: Opaque version tag; changes whenever the content is replaced.
        last_modified: When the object was last written (timezone-aware, UTC).
        metadata: User-defined string metadata recorded at upload.
    """

    model_config = ConfigDict(frozen=True)

    key: str
    size: int
    content_type: str | None = None
    etag: str | None = None
    last_modified: datetime
    metadata: dict[str, str] = Field(default_factory=dict)


def _validate_path(value: str, *, what: str, allow_trailing_slash: bool) -> str:
    if not isinstance(value, str):
        raise InvalidStorageKeyError(f"{what} must be a string")
    if len(value) > MAX_KEY_LENGTH:
        raise InvalidStorageKeyError(f"{what} is longer than {MAX_KEY_LENGTH} characters")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise InvalidStorageKeyError(f"{what} contains a control character")
    if "\\" in value:
        raise InvalidStorageKeyError(f"{what} must use '/' separators, not '\\'")
    if value.startswith("/"):
        raise InvalidStorageKeyError(f"{what} must be relative (no leading '/')")
    if _DRIVE_PREFIX.match(value):
        raise InvalidStorageKeyError(f"{what} must not start with a drive prefix")
    body = value[:-1] if allow_trailing_slash and value.endswith("/") else value
    if body.endswith("/"):
        raise InvalidStorageKeyError(f"{what} must not end with '/'")
    for segment in body.split("/"):
        if segment == "":
            raise InvalidStorageKeyError(f"{what} contains an empty path segment")
        if segment in (".", ".."):
            raise InvalidStorageKeyError(f"{what} contains a '.' or '..' segment")
    return value


def validate_key(key: str) -> str:
    """Validate an object key and return it unchanged.

    A key is one or more non-empty `/`-separated segments. Rejected: empty keys,
    keys over `MAX_KEY_LENGTH`, a leading or trailing `/`, `\\`, control
    characters (including NUL), `.`/`..` segments, empty segments, and drive
    prefixes like `C:`. Validation runs before any provider sees the key, so
    both providers accept exactly the same keys and a key can never name a
    location outside the storage root.

    Args:
        key: The object key to validate.

    Returns:
        `key`, unchanged.

    Raises:
        InvalidStorageKeyError: If `key` is not a valid object key.
    """
    if not key:
        raise InvalidStorageKeyError("key must not be empty")
    return _validate_path(key, what="key", allow_trailing_slash=False)


def validate_prefix(prefix: str) -> str:
    """Validate a list prefix and return it unchanged.

    An empty prefix lists everything. Otherwise the same rules as
    `validate_key()` apply, except that a single trailing `/` is allowed
    (`documents/`); a partial segment (`documents/do`) is also allowed.

    Args:
        prefix: The list prefix to validate.

    Returns:
        `prefix`, unchanged.

    Raises:
        InvalidStorageKeyError: If `prefix` is not a valid list prefix.
    """
    if prefix == "":
        return prefix
    return _validate_path(prefix, what="prefix", allow_trailing_slash=True)


def validate_metadata(metadata: Mapping[str, str] | None) -> dict[str, str]:
    """Validate user metadata and return it as a plain dict.

    Keys must be ASCII identifiers and values ASCII strings - Azure Blob's
    rules, enforced for every provider so metadata that works on one works on
    all. Keys are case-insensitive in Azure, so keys differing only by case are
    rejected too.

    Args:
        metadata: The user metadata to validate, or `None` for none.

    Returns:
        A new `dict` holding the validated entries.

    Raises:
        InvalidStorageKeyError: If a key or value is invalid.
    """
    if not metadata:
        return {}
    seen: set[str] = set()
    for name, value in metadata.items():
        if not isinstance(name, str) or not _METADATA_KEY.match(name):
            raise InvalidStorageKeyError(
                f"metadata key {name!r} must be an ASCII identifier"
            )
        if name.lower() in seen:
            raise InvalidStorageKeyError(
                f"metadata key {name!r} duplicates another key ignoring case"
            )
        seen.add(name.lower())
        if not isinstance(value, str) or not value.isascii():
            raise InvalidStorageKeyError(f"metadata value for {name!r} must be an ASCII string")
    return dict(metadata)


class StorageService(ABC):
    """Provider-agnostic object storage.

    Implementations: `FileSystemStorage` (`storage/filesystem.py`) and
    `AzureBlobStorage` (`storage/azure_blob.py`); build one from configuration
    with `create_storage_service()` (`storage/factory.py`). Every key argument is
    validated with `validate_key()` before the provider touches it.

    Missing objects: `download()`, `read_bytes()` and `get_metadata()` raise
    `StorageObjectNotFoundError`; `delete()` and `exists()` report absence
    through their return value instead.

    Usable as an async context manager, which calls `aclose()` on exit.
    """

    @abstractmethod
    async def upload(
        self,
        key: str,
        data: bytes | AsyncIterable[bytes],
        *,
        content_type: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> ObjectMetadata:
        """Store an object, replacing any existing object with the same key.

        Args:
            key: The object key.
            data: The content, either in memory or as an async stream of chunks.
                Stream large files - providers never buffer a whole stream.
            content_type: MIME type to record with the object.
            metadata: User metadata to record (see `validate_metadata()`).

        Returns:
            The stored object's metadata.

        Raises:
            InvalidStorageKeyError: If `key` or `metadata` is invalid.
        """

    @abstractmethod
    def download(self, key: str, *, chunk_size: int = DEFAULT_CHUNK_SIZE) -> AsyncIterator[bytes]:
        """Stream an object's content.

        Args:
            key: The object key.
            chunk_size: Preferred chunk size in bytes. Providers may yield
                smaller chunks.

        Yields:
            The content, in order.

        Raises:
            InvalidStorageKeyError: If `key` is invalid.
            StorageObjectNotFoundError: If no object exists at `key`.
        """

    async def read_bytes(self, key: str) -> bytes:
        """Read an object's whole content into memory.

        Convenience for small objects; stream large ones with `download()`.

        Args:
            key: The object key.

        Returns:
            The object's content.

        Raises:
            InvalidStorageKeyError: If `key` is invalid.
            StorageObjectNotFoundError: If no object exists at `key`.
        """
        return b"".join([chunk async for chunk in self.download(key)])

    @abstractmethod
    async def delete(self, key: str) -> bool:
        """Delete an object. Idempotent.

        Args:
            key: The object key.

        Returns:
            `True` if an object was deleted, `False` if none existed.

        Raises:
            InvalidStorageKeyError: If `key` is invalid.
        """

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Report whether an object exists.

        Args:
            key: The object key.

        Returns:
            `True` if an object exists at `key`.

        Raises:
            InvalidStorageKeyError: If `key` is invalid.
        """

    @abstractmethod
    def list(self, prefix: str = "") -> AsyncIterator[ObjectMetadata]:
        """List objects whose key starts with `prefix`, in lexicographic key order.

        The match is a plain string prefix, not a directory: `documents/do`
        matches `documents/doc-1/a.pdf`.

        Args:
            prefix: The key prefix; empty lists every object.

        Yields:
            Metadata for each matching object.

        Raises:
            InvalidStorageKeyError: If `prefix` is invalid.
        """

    @abstractmethod
    async def get_metadata(self, key: str) -> ObjectMetadata:
        """Read an object's metadata without its content.

        Args:
            key: The object key.

        Returns:
            The object's metadata.

        Raises:
            InvalidStorageKeyError: If `key` is invalid.
            StorageObjectNotFoundError: If no object exists at `key`.
        """

    async def aclose(self) -> None:
        """Release any network clients or credentials the provider holds."""

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()


__all__ = [
    "DEFAULT_CHUNK_SIZE",
    "InvalidStorageKeyError",
    "MAX_KEY_LENGTH",
    "ObjectMetadata",
    "StorageError",
    "StorageObjectNotFoundError",
    "StorageService",
    "validate_key",
    "validate_metadata",
    "validate_prefix",
]
