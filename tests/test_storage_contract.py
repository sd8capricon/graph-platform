"""Provider contract tests: every `StorageService` must pass the same suite.

`filesystem` always runs (against `tmp_path`). `azure_blob` runs against Azurite
when `AZURITE_CONNECTION_STRING` is set, and is skipped otherwise - see the Storage
Pattern section of CLAUDE.md for how to start Azurite.
"""

import hashlib
import os
import uuid

import pytest

from common.schemas.storage import AzureBlobAuthMode, AzureBlobStorageSettings
from common.storage.base import (
    InvalidStorageKeyError,
    StorageObjectNotFoundError,
    StorageService,
)
from common.storage.filesystem import FileSystemStorage

AZURITE_ENV = "AZURITE_CONNECTION_STRING"
KEY = "documents/doc-1/file-1/content.pdf"
MISSING_KEY = "documents/missing/file/content.pdf"
LARGE_FILE_SIZE = 20 * 1024 * 1024
SMALL_BLOCK_SIZE = 256 * 1024

INVALID_KEYS = [
    "",
    "/documents/a.pdf",
    "documents/a.pdf/",
    "../etc/passwd",
    "documents/../../etc/passwd",
    "documents/./a.pdf",
    "documents//a.pdf",
    "documents\\a.pdf",
    "..\\..\\windows\\win.ini",
    "C:/windows/win.ini",
    "documents/a\x00.pdf",
    "documents/a\n.pdf",
    "a" * 1025,
]


@pytest.fixture(params=["filesystem", "azure_blob"])
async def storage(request, tmp_path):
    """Yield `(storage, forbidden)`: a provider and strings its metadata must never contain."""
    if request.param == "filesystem":
        async with FileSystemStorage(tmp_path / "storage") as provider:
            yield provider, [str(tmp_path)]
        return

    connection_string = os.environ.get(AZURITE_ENV)
    if not connection_string:
        pytest.skip(f"{AZURITE_ENV} is not set; start Azurite to run Azure contract tests")
    from azure.storage.blob.aio import BlobServiceClient

    from common.storage.azure_blob import AzureBlobStorage

    container = f"contract-{uuid.uuid4().hex[:16]}"
    settings = AzureBlobStorageSettings(
        auth_mode=AzureBlobAuthMode.CONNECTION_STRING,
        connection_string=connection_string,
        container=container,
        create_container=True,
        max_block_size=SMALL_BLOCK_SIZE,
        max_single_put_size=SMALL_BLOCK_SIZE,
    )
    try:
        async with AzureBlobStorage(settings) as provider:
            yield provider, ["http://", "https://", "AccountKey"]
    finally:
        async with BlobServiceClient.from_connection_string(connection_string) as client:
            try:
                await client.delete_container(container)
            except Exception:
                pass


async def _chunks(*parts: bytes):
    for part in parts:
        yield part


async def _keys(storage: StorageService, prefix: str = "") -> list[str]:
    return [item.key async for item in storage.list(prefix)]


async def test_upload_and_download_bytes_round_trip(storage):
    provider, _ = storage

    metadata = await provider.upload(KEY, b"hello world")

    assert metadata.key == KEY
    assert metadata.size == 11
    assert metadata.etag
    assert metadata.last_modified.tzinfo is not None
    assert await provider.read_bytes(KEY) == b"hello world"


async def test_upload_accepts_an_async_stream(storage):
    provider, _ = storage

    metadata = await provider.upload(KEY, _chunks(b"hello ", b"streamed ", b"world"))

    assert metadata.size == len(b"hello streamed world")
    assert await provider.read_bytes(KEY) == b"hello streamed world"


async def test_upload_of_an_empty_stream_stores_an_empty_object(storage):
    provider, _ = storage

    metadata = await provider.upload(KEY, _chunks())

    assert metadata.size == 0
    assert await provider.read_bytes(KEY) == b""


async def test_upload_overwrites_content_and_metadata(storage):
    provider, _ = storage
    first = await provider.upload(
        KEY, b"version one", content_type="text/plain", metadata={"version": "1"}
    )

    second = await provider.upload(
        KEY, b"version two!", content_type="application/pdf", metadata={"version": "2"}
    )

    assert await provider.read_bytes(KEY) == b"version two!"
    current = await provider.get_metadata(KEY)
    assert current.size == len(b"version two!")
    assert current.content_type == "application/pdf"
    assert current.metadata == {"version": "2"}
    assert second.etag != first.etag
    assert await _keys(provider) == [KEY]


async def test_content_type_and_metadata_round_trip(storage):
    provider, forbidden = storage

    uploaded = await provider.upload(
        KEY,
        b"%PDF-1.7",
        content_type="application/pdf",
        metadata={"document_id": "doc-1", "original_name": "report.pdf"},
    )
    fetched = await provider.get_metadata(KEY)

    for metadata in (uploaded, fetched):
        assert metadata.key == KEY
        assert metadata.size == 8
        assert metadata.content_type == "application/pdf"
        assert metadata.metadata == {"document_id": "doc-1", "original_name": "report.pdf"}
        # The canonical reference is the key: no physical path or URL leaks out.
        dumped = metadata.model_dump_json()
        assert not any(value in dumped for value in forbidden)
    assert fetched.etag == uploaded.etag


async def test_exists_reports_presence(storage):
    provider, _ = storage

    assert await provider.exists(KEY) is False
    await provider.upload(KEY, b"data")

    assert await provider.exists(KEY) is True
    assert await provider.exists("documents/doc-1") is False  # a prefix is not an object


async def test_delete_removes_the_object_and_is_idempotent(storage):
    provider, _ = storage
    await provider.upload(KEY, b"data")
    await provider.upload("documents/doc-1/file-2/content.pdf", b"other")

    assert await provider.delete(KEY) is True
    assert await provider.delete(KEY) is False
    assert await provider.exists(KEY) is False
    assert await _keys(provider) == ["documents/doc-1/file-2/content.pdf"]


async def test_delete_of_a_missing_object_returns_false(storage):
    provider, _ = storage

    assert await provider.delete(MISSING_KEY) is False


async def test_list_by_prefix_returns_matching_objects_in_key_order(storage):
    provider, _ = storage
    keys = [
        "documents/doc-2/file-1/content.pdf",
        "documents/doc-1/file-2/content.pdf",
        "documents/doc-1/file-1/content.pdf",
        "documents/doc-10/file-1/content.pdf",
        "images/doc-1/thumb.png",
    ]
    for index, key in enumerate(keys):
        await provider.upload(key, b"x" * (index + 1), metadata={"n": str(index)})

    listed = [item async for item in provider.list("documents/doc-1/")]

    assert [item.key for item in listed] == [
        "documents/doc-1/file-1/content.pdf",
        "documents/doc-1/file-2/content.pdf",
    ]
    assert [item.size for item in listed] == [3, 2]
    assert [item.metadata for item in listed] == [{"n": "2"}, {"n": "1"}]
    assert await _keys(provider, "documents/") == sorted(keys[:4])
    assert await _keys(provider) == sorted(keys)


async def test_list_matches_a_partial_segment_prefix(storage):
    provider, _ = storage
    for key in ("documents/doc-1/a.pdf", "documents/doc-10/a.pdf", "documents/other/a.pdf"):
        await provider.upload(key, b"x")

    assert await _keys(provider, "documents/doc-1") == [
        "documents/doc-1/a.pdf",
        "documents/doc-10/a.pdf",
    ]
    assert await _keys(provider, "doc") == [
        "documents/doc-1/a.pdf",
        "documents/doc-10/a.pdf",
        "documents/other/a.pdf",
    ]


async def test_list_of_an_unknown_prefix_is_empty(storage):
    provider, _ = storage

    assert await _keys(provider) == []
    await provider.upload(KEY, b"x")
    assert await _keys(provider, "nothing/here/") == []


async def test_missing_objects_raise_not_found(storage):
    provider, _ = storage

    with pytest.raises(StorageObjectNotFoundError) as download_error:
        async for _ in provider.download(MISSING_KEY):
            pass
    with pytest.raises(StorageObjectNotFoundError):
        await provider.read_bytes(MISSING_KEY)
    with pytest.raises(StorageObjectNotFoundError):
        await provider.get_metadata(MISSING_KEY)
    assert download_error.value.key == MISSING_KEY


@pytest.mark.parametrize("key", INVALID_KEYS)
async def test_invalid_and_traversal_keys_are_rejected_by_every_operation(storage, key):
    provider, _ = storage

    with pytest.raises(InvalidStorageKeyError):
        await provider.upload(key, b"x")
    with pytest.raises(InvalidStorageKeyError):
        async for _ in provider.download(key):
            pass
    with pytest.raises(InvalidStorageKeyError):
        await provider.delete(key)
    with pytest.raises(InvalidStorageKeyError):
        await provider.exists(key)
    with pytest.raises(InvalidStorageKeyError):
        await provider.get_metadata(key)
    assert await _keys(provider) == []


@pytest.mark.parametrize("prefix", ["/documents", "../", "documents//", "documents\\", "a/../b"])
async def test_invalid_list_prefixes_are_rejected(storage, prefix):
    provider, _ = storage

    with pytest.raises(InvalidStorageKeyError):
        await _keys(provider, prefix)


@pytest.mark.parametrize(
    "metadata",
    [{"has-dash": "x"}, {"1starts_with_digit": "x"}, {"ok": "non-ascii é"}, {"a": "1", "A": "2"}],
)
async def test_invalid_metadata_is_rejected(storage, metadata):
    provider, _ = storage

    with pytest.raises(InvalidStorageKeyError):
        await provider.upload(KEY, b"x", metadata=metadata)
    assert await provider.exists(KEY) is False


async def test_large_files_stream_in_both_directions(storage):
    provider, _ = storage
    chunk_size = 1024 * 1024
    upload_digest = hashlib.sha256()

    async def generate():
        for _ in range(LARGE_FILE_SIZE // chunk_size):
            chunk = os.urandom(chunk_size)
            upload_digest.update(chunk)
            yield chunk

    metadata = await provider.upload(KEY, generate(), content_type="application/octet-stream")

    download_digest = hashlib.sha256()
    chunks = 0
    async for chunk in provider.download(KEY, chunk_size=chunk_size):
        assert len(chunk) <= chunk_size
        download_digest.update(chunk)
        chunks += 1
    assert metadata.size == LARGE_FILE_SIZE
    assert (await provider.get_metadata(KEY)).size == LARGE_FILE_SIZE
    assert download_digest.hexdigest() == upload_digest.hexdigest()
    assert chunks >= LARGE_FILE_SIZE // chunk_size
