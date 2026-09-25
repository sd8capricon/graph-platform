"""`StorageService` backed by one Azure Blob Storage container."""

import asyncio
import uuid
from collections.abc import AsyncIterable, AsyncIterator, Mapping
from typing import Any

from azure.core.exceptions import (
    AzureError,
    HttpResponseError,
    ResourceExistsError,
    ResourceNotFoundError,
)
from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob import BlobBlock, BlobProperties, ContentSettings
from azure.storage.blob.aio import BlobServiceClient

from common.schemas.storage import AzureBlobAuthMode, AzureBlobStorageSettings
from common.storage.base import (
    DEFAULT_CHUNK_SIZE,
    ObjectMetadata,
    StorageError,
    StorageObjectNotFoundError,
    StorageService,
    validate_key,
    validate_metadata,
    validate_prefix,
)


def _storage_error(operation: str, exc: AzureError) -> StorageError:
    """Wrap an Azure SDK error without echoing request details.

    Only the operation, status and service error code are kept - never the
    request URL or headers - so no account detail or credential reaches logs.
    """
    status = exc.status_code if isinstance(exc, HttpResponseError) else None
    error_code = getattr(exc, "error_code", None)
    detail = ", ".join(
        part
        for part in (f"status {status}" if status else None, str(error_code) if error_code else None)
        if part
    )
    message = f"azure blob {operation} failed"
    return StorageError(
        f"{message} ({detail})" if detail else f"{message} ({type(exc).__name__})",
        status_code=status,
    )


class AzureBlobStorage(StorageService):
    """Object storage in one Azure Blob Storage container.

    Object keys map 1:1 onto blob names; no blob URL is ever returned or
    persisted. Authentication is either a connection string (development,
    Azurite) or `DefaultAzureCredential` (managed identity in Azure) - see
    `AzureBlobStorageSettings`.

    Streamed uploads are staged block by block (`max_block_size` each) and made
    visible with one `commit_block_list`, so memory stays bounded and readers
    never see a partial blob; a failed upload leaves the previous blob intact
    (Azure discards the uncommitted blocks).
    """

    def __init__(self, settings: AzureBlobStorageSettings):
        """Create the storage client. Performs no I/O.

        Args:
            settings: Azure Blob configuration.

        Raises:
            ValueError: If `settings` lacks what its `auth_mode` needs.
        """
        settings.ensure_credentials()
        self._settings = settings
        client_options: dict[str, Any] = {
            "max_block_size": settings.max_block_size,
            "max_single_put_size": settings.max_single_put_size,
        }
        self._credential: DefaultAzureCredential | None = None
        if settings.auth_mode == AzureBlobAuthMode.CONNECTION_STRING:
            assert settings.connection_string is not None  # ensured above
            self._client = BlobServiceClient.from_connection_string(
                settings.connection_string.get_secret_value(), **client_options
            )
        else:
            assert settings.account_url is not None  # ensured above
            self._credential = DefaultAzureCredential(
                managed_identity_client_id=settings.managed_identity_client_id
            )
            self._client = BlobServiceClient(
                settings.account_url, credential=self._credential, **client_options
            )
        self._container = self._client.get_container_client(settings.container)
        self._container_ready = not settings.create_container
        self._container_lock = asyncio.Lock()

    def __repr__(self) -> str:
        # Deliberately omits the account URL and any credential.
        return f"{type(self).__name__}(container={self._settings.container!r})"

    async def _ensure_container(self) -> None:
        if self._container_ready:
            return
        async with self._container_lock:
            if self._container_ready:
                return
            try:
                await self._container.create_container()
            except ResourceExistsError:
                pass
            except AzureError as exc:
                raise _storage_error("create container", exc) from None
            self._container_ready = True

    @staticmethod
    def _to_metadata(key: str, properties: BlobProperties) -> ObjectMetadata:
        content_settings = properties.content_settings
        return ObjectMetadata(
            key=key,
            size=properties.size,
            content_type=content_settings.content_type if content_settings else None,
            etag=properties.etag,
            last_modified=properties.last_modified,
            metadata=dict(properties.metadata or {}),
        )

    async def upload(
        self,
        key: str,
        data: bytes | AsyncIterable[bytes],
        *,
        content_type: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> ObjectMetadata:
        validate_key(key)
        user_metadata = validate_metadata(metadata)
        content_settings = ContentSettings(content_type=content_type)
        await self._ensure_container()
        blob = self._container.get_blob_client(key)
        try:
            if isinstance(data, (bytes, bytearray, memoryview)):
                await blob.upload_blob(
                    bytes(data),
                    overwrite=True,
                    metadata=user_metadata,
                    content_settings=content_settings,
                    max_concurrency=self._settings.max_concurrency,
                )
            else:
                await self._upload_stream(blob, data, user_metadata, content_settings)
            properties = await blob.get_blob_properties()
        except AzureError as exc:
            raise _storage_error("upload", exc) from None
        return self._to_metadata(key, properties)

    async def _upload_stream(
        self,
        blob: Any,
        data: AsyncIterable[bytes],
        metadata: dict[str, str],
        content_settings: ContentSettings,
    ) -> None:
        # Block ids must share one length within a blob; a per-upload nonce keeps
        # a concurrent upload of the same key from committing our blocks.
        nonce = uuid.uuid4().hex
        block_size = self._settings.max_block_size
        blocks: list[BlobBlock] = []
        buffer = bytearray()

        async def stage(payload: bytes) -> None:
            block_id = f"{nonce}-{len(blocks):08d}"
            await blob.stage_block(block_id, payload, length=len(payload))
            blocks.append(BlobBlock(block_id=block_id))

        async for chunk in data:
            buffer.extend(chunk)
            while len(buffer) >= block_size:
                await stage(bytes(buffer[:block_size]))
                del buffer[:block_size]
        if buffer or not blocks:
            await stage(bytes(buffer))
        await blob.commit_block_list(
            blocks, content_settings=content_settings, metadata=metadata
        )

    async def download(
        self, key: str, *, chunk_size: int = DEFAULT_CHUNK_SIZE
    ) -> AsyncIterator[bytes]:
        validate_key(key)
        blob = self._container.get_blob_client(key)
        try:
            downloader = await blob.download_blob(max_concurrency=self._settings.max_concurrency)
        except ResourceNotFoundError:
            raise StorageObjectNotFoundError(key) from None
        except AzureError as exc:
            raise _storage_error("download", exc) from None
        try:
            async for chunk in downloader.chunks():
                for start in range(0, len(chunk), chunk_size):
                    yield chunk[start : start + chunk_size]
        except AzureError as exc:
            raise _storage_error("download", exc) from None

    async def delete(self, key: str) -> bool:
        validate_key(key)
        try:
            await self._container.delete_blob(key, delete_snapshots="include")
        except ResourceNotFoundError:
            return False
        except AzureError as exc:
            raise _storage_error("delete", exc) from None
        return True

    async def exists(self, key: str) -> bool:
        validate_key(key)
        try:
            return await self._container.get_blob_client(key).exists()
        except AzureError as exc:
            raise _storage_error("exists", exc) from None

    async def list(self, prefix: str = "") -> AsyncIterator[ObjectMetadata]:
        validate_prefix(prefix)
        try:
            async for properties in self._container.list_blobs(
                name_starts_with=prefix or None, include=["metadata"]
            ):
                yield self._to_metadata(properties.name, properties)
        except ResourceNotFoundError:
            return  # container not created yet: nothing stored
        except AzureError as exc:
            raise _storage_error("list", exc) from None

    async def get_metadata(self, key: str) -> ObjectMetadata:
        validate_key(key)
        try:
            properties = await self._container.get_blob_client(key).get_blob_properties()
        except ResourceNotFoundError:
            raise StorageObjectNotFoundError(key) from None
        except AzureError as exc:
            raise _storage_error("get metadata", exc) from None
        return self._to_metadata(key, properties)

    async def aclose(self) -> None:
        await self._client.close()
        if self._credential is not None:
            await self._credential.close()


__all__ = ["AzureBlobStorage"]
