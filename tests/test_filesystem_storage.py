"""`FileSystemStorage`-specific behavior beyond the provider contract."""

import json
import os

import pytest

from common.storage.base import InvalidStorageKeyError, StorageError
from common.storage.filesystem import FileSystemStorage

KEY = "documents/doc-1/file-1/content.pdf"


async def test_objects_sidecars_and_staging_use_the_documented_layout(tmp_path):
    storage = FileSystemStorage(tmp_path)

    await storage.upload(KEY, b"data", content_type="application/pdf", metadata={"a": "b"})

    assert (tmp_path / "objects" / KEY).read_bytes() == b"data"
    sidecar = json.loads((tmp_path / "meta" / KEY).read_bytes())
    assert sidecar["content_type"] == "application/pdf"
    assert sidecar["metadata"] == {"a": "b"}
    assert list((tmp_path / "tmp").iterdir()) == []


async def test_a_symlink_escaping_the_root_is_rejected(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"secret")
    storage = FileSystemStorage(tmp_path / "storage")
    (tmp_path / "storage" / "objects" / "documents").symlink_to(outside)

    with pytest.raises(InvalidStorageKeyError):
        await storage.read_bytes("documents/secret.txt")
    with pytest.raises(InvalidStorageKeyError):
        await storage.upload("documents/new.txt", b"x")
    with pytest.raises(InvalidStorageKeyError):
        await storage.delete("documents/secret.txt")
    assert [item async for item in storage.list()] == []
    assert (outside / "secret.txt").read_bytes() == b"secret"
    assert not (outside / "new.txt").exists()


async def test_a_failed_streamed_upload_keeps_the_previous_version(tmp_path):
    storage = FileSystemStorage(tmp_path)
    await storage.upload(KEY, b"previous", metadata={"version": "1"})

    async def failing():
        yield b"partial new content"
        raise RuntimeError("client disconnected")

    with pytest.raises(RuntimeError, match="client disconnected"):
        await storage.upload(KEY, failing(), metadata={"version": "2"})

    assert await storage.read_bytes(KEY) == b"previous"
    assert (await storage.get_metadata(KEY)).metadata == {"version": "1"}
    assert list((tmp_path / "tmp").iterdir()) == []


async def test_a_failed_first_upload_leaves_no_object(tmp_path):
    storage = FileSystemStorage(tmp_path)

    async def failing():
        yield b"partial"
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await storage.upload(KEY, failing())

    assert await storage.exists(KEY) is False
    assert list((tmp_path / "tmp").iterdir()) == []


async def test_metadata_falls_back_to_stat_when_the_sidecar_is_missing(tmp_path):
    storage = FileSystemStorage(tmp_path)
    await storage.upload(KEY, b"data", content_type="application/pdf", metadata={"a": "b"})
    (tmp_path / "meta" / KEY).unlink()

    metadata = await storage.get_metadata(KEY)

    assert metadata.size == 4
    assert metadata.content_type is None
    assert metadata.metadata == {}
    assert metadata.etag


async def test_a_stale_sidecar_is_ignored(tmp_path):
    storage = FileSystemStorage(tmp_path)
    await storage.upload(KEY, b"data", content_type="application/pdf")
    # Simulate a crash between replacing the content and replacing its sidecar.
    (tmp_path / "objects" / KEY).write_bytes(b"newer content")

    metadata = await storage.get_metadata(KEY)

    assert metadata.size == len(b"newer content")
    assert metadata.content_type is None


async def test_delete_prunes_empty_directories(tmp_path):
    storage = FileSystemStorage(tmp_path)
    await storage.upload(KEY, b"data")
    await storage.upload("documents/doc-2/a.pdf", b"data")

    await storage.delete(KEY)

    assert not (tmp_path / "objects" / "documents" / "doc-1").exists()
    assert not (tmp_path / "meta" / "documents" / "doc-1").exists()
    assert (tmp_path / "objects" / "documents" / "doc-2" / "a.pdf").exists()
    assert (tmp_path / "objects").is_dir()


async def test_a_key_that_is_a_prefix_of_another_key_is_refused(tmp_path):
    storage = FileSystemStorage(tmp_path)
    await storage.upload("documents/doc-1", b"file")

    with pytest.raises(StorageError, match="conflicts"):
        await storage.upload("documents/doc-1/nested.pdf", b"x")
    assert await storage.read_bytes("documents/doc-1") == b"file"


async def test_a_relative_root_resolves_against_the_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    storage = FileSystemStorage("data/storage")
    await storage.upload(KEY, b"data")

    assert (tmp_path / "data" / "storage" / "objects" / KEY).is_file()
    assert os.fspath(tmp_path) in repr(storage)
