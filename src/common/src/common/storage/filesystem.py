"""`StorageService` backed by a local (or volume-mounted) directory."""

import asyncio
import hashlib
import json
import os
import uuid
from collections.abc import AsyncIterable, AsyncIterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from common.storage.base import (
    DEFAULT_CHUNK_SIZE,
    InvalidStorageKeyError,
    ObjectMetadata,
    StorageError,
    StorageObjectNotFoundError,
    StorageService,
    validate_key,
    validate_metadata,
    validate_prefix,
)

OBJECTS_DIR = "objects"
META_DIR = "meta"
TMP_DIR = "tmp"


class FileSystemStorage(StorageService):
    """Object storage in a directory tree.

    Layout under `root`:

    - `objects/<key>` - the object's content, one file per key.
    - `meta/<key>` - a JSON sidecar (content type, user metadata, etag, and the
      size/mtime it describes), mirroring the `objects/` tree exactly.
    - `tmp/` - staging for in-progress writes.

    Writes are atomic: content streams to `tmp/`, is fsynced, then moved over
    `objects/<key>` with `os.replace`, so readers see the old object or the new
    one, never a partial file, and a failed upload leaves the previous version
    intact. Staging inside `root` keeps that rename on one filesystem, which is
    what makes it atomic on a Docker volume too - mount the volume at `root`,
    not at `root/objects`.

    The sidecar is written after the content. If a crash lands between the two,
    the sidecar no longer matches the content's size/mtime and is ignored:
    metadata then falls back to `stat` with no content type or user metadata.

    Path safety: keys pass `validate_key()` (no `..`, absolute paths, `\\`, ...),
    any existing path component under `objects/`/`meta/` that is a symlink is
    rejected, and the final path must resolve inside the tree.

    Limitation: a filesystem cannot hold both a file `a` and a directory `a`, so
    one key cannot be a strict `/`-prefix of another (`a` and `a/b`). Uploading
    such a key raises `StorageError`. Azure Blob has no such restriction.
    """

    def __init__(self, root: str | Path):
        """Create the storage, creating its directory layout if missing.

        Args:
            root: Directory holding every stored object. Relative paths resolve
                against the working directory.
        """
        self._root = Path(root).expanduser().resolve()
        self._objects = self._root / OBJECTS_DIR
        self._meta = self._root / META_DIR
        self._tmp = self._root / TMP_DIR
        for directory in (self._objects, self._meta, self._tmp):
            directory.mkdir(parents=True, exist_ok=True)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(root={str(self._root)!r})"

    # Path resolution ----------------------------------------------------------

    @staticmethod
    def _safe_join(base: Path, relative: str) -> Path:
        """Join a validated `/`-separated relative path onto `base`, refusing symlinks.

        Raises:
            InvalidStorageKeyError: If a component is a symlink or the result
                resolves outside `base`.
        """
        path = base
        for segment in relative.split("/"):
            path = path / segment
            if path.is_symlink():
                raise InvalidStorageKeyError("key traverses a symbolic link")
        if not path.resolve().is_relative_to(base):
            raise InvalidStorageKeyError("key resolves outside the storage root")
        return path

    def _paths(self, key: str) -> tuple[Path, Path]:
        validate_key(key)
        return self._safe_join(self._objects, key), self._safe_join(self._meta, key)

    # Blocking helpers (run via asyncio.to_thread) -----------------------------

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        """Persist a rename by fsyncing its directory (best-effort; POSIX only)."""
        try:
            fd = os.open(directory, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(fd)
        except OSError:
            pass
        finally:
            os.close(fd)

    def _commit(self, temp: Path, destination: Path) -> None:
        """Atomically move a staged file into place, creating parent directories."""
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
        except (FileExistsError, NotADirectoryError) as exc:
            raise StorageError(
                "key conflicts with an existing key (one key cannot be a '/'-prefix of another)"
            ) from exc
        if destination.is_dir():
            raise StorageError(
                "key conflicts with an existing key (one key cannot be a '/'-prefix of another)"
            )
        os.replace(temp, destination)
        self._fsync_directory(destination.parent)

    def _write_sidecar(self, meta_path: Path, sidecar: dict[str, Any]) -> None:
        temp = self._tmp / f"{uuid.uuid4().hex}.meta"
        try:
            with open(temp, "xb") as handle:
                handle.write(json.dumps(sidecar).encode())
                handle.flush()
                os.fsync(handle.fileno())
            self._commit(temp, meta_path)
        finally:
            temp.unlink(missing_ok=True)

    @staticmethod
    def _read_sidecar(meta_path: Path, stat: os.stat_result) -> dict[str, Any]:
        """Read a sidecar, or `{}` if missing, corrupt, or describing older content."""
        try:
            sidecar = json.loads(meta_path.read_bytes())
        except (OSError, ValueError):
            return {}
        if not isinstance(sidecar, dict):
            return {}
        mtime_ns = sidecar.get("mtime_ns")
        # Compared at 100 ns resolution: other writers of this layout (the .NET API's
        # FileSystemStorage) record file times as 100 ns ticks.
        if (
            sidecar.get("size") != stat.st_size
            or not isinstance(mtime_ns, int)
            or mtime_ns // 100 != stat.st_mtime_ns // 100
        ):
            return {}
        return sidecar

    def _metadata_sync(self, key: str, object_path: Path, meta_path: Path) -> ObjectMetadata:
        try:
            stat = object_path.stat()
        except (FileNotFoundError, NotADirectoryError):
            raise StorageObjectNotFoundError(key) from None
        if not object_path.is_file():
            raise StorageObjectNotFoundError(key)
        sidecar = self._read_sidecar(meta_path, stat)
        metadata = sidecar.get("metadata")
        return ObjectMetadata(
            key=key,
            size=stat.st_size,
            content_type=sidecar.get("content_type"),
            etag=sidecar.get("etag") or f"{stat.st_mtime_ns:x}-{stat.st_size:x}",
            last_modified=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
            metadata=metadata if isinstance(metadata, dict) else {},
        )

    def _delete_sync(self, object_path: Path, meta_path: Path) -> bool:
        if not object_path.is_file():
            return False
        try:
            object_path.unlink()
        except FileNotFoundError:
            return False
        meta_path.unlink(missing_ok=True)
        self._prune(object_path.parent, self._objects)
        self._prune(meta_path.parent, self._meta)
        return True

    @staticmethod
    def _prune(directory: Path, stop: Path) -> None:
        """Remove now-empty parent directories up to (not including) `stop`. Best-effort."""
        while directory != stop and directory.is_relative_to(stop):
            try:
                directory.rmdir()
            except OSError:
                return
            directory = directory.parent

    def _list_keys_sync(self, prefix: str) -> list[str]:
        # Walk only the deepest directory the prefix fully names, then filter by
        # string prefix, so `documents/do` still matches `documents/doc-1/...`.
        directory_part = prefix.rsplit("/", 1)[0] if "/" in prefix else ""
        start = self._safe_join(self._objects, directory_part) if directory_part else self._objects
        if not start.is_dir():
            return []
        keys: list[str] = []
        for current, directories, files in os.walk(start, followlinks=False):
            current_path = Path(current)
            directories[:] = [d for d in directories if not (current_path / d).is_symlink()]
            for name in files:
                path = current_path / name
                if path.is_symlink():
                    continue
                key = path.relative_to(self._objects).as_posix()
                if key.startswith(prefix):
                    keys.append(key)
        keys.sort()
        return keys

    # StorageService -----------------------------------------------------------

    async def upload(
        self,
        key: str,
        data: bytes | AsyncIterable[bytes],
        *,
        content_type: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> ObjectMetadata:
        object_path, meta_path = await asyncio.to_thread(self._paths, key)
        user_metadata = validate_metadata(metadata)
        temp = self._tmp / f"{uuid.uuid4().hex}.part"
        digest = hashlib.md5(usedforsecurity=False)
        handle = await asyncio.to_thread(open, temp, "xb")
        try:
            try:
                if isinstance(data, (bytes, bytearray, memoryview)):
                    digest.update(data)
                    await asyncio.to_thread(handle.write, data)
                else:
                    async for chunk in data:
                        digest.update(chunk)
                        await asyncio.to_thread(handle.write, chunk)
                await asyncio.to_thread(handle.flush)
                await asyncio.to_thread(os.fsync, handle.fileno())
            finally:
                await asyncio.to_thread(handle.close)
            stat = await asyncio.to_thread(temp.stat)
            await asyncio.to_thread(self._commit, temp, object_path)
        finally:
            await asyncio.to_thread(temp.unlink, missing_ok=True)

        await asyncio.to_thread(
            self._write_sidecar,
            meta_path,
            {
                "content_type": content_type,
                "metadata": user_metadata,
                "etag": digest.hexdigest(),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            },
        )
        return await asyncio.to_thread(self._metadata_sync, key, object_path, meta_path)

    async def download(
        self, key: str, *, chunk_size: int = DEFAULT_CHUNK_SIZE
    ) -> AsyncIterator[bytes]:
        object_path, _ = await asyncio.to_thread(self._paths, key)
        try:
            handle = await asyncio.to_thread(open, object_path, "rb")
        except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
            raise StorageObjectNotFoundError(key) from None
        except PermissionError:
            # Windows reports opening a directory as PermissionError.
            if await asyncio.to_thread(object_path.is_dir):
                raise StorageObjectNotFoundError(key) from None
            raise
        try:
            while chunk := await asyncio.to_thread(handle.read, chunk_size):
                yield chunk
        finally:
            await asyncio.to_thread(handle.close)

    async def delete(self, key: str) -> bool:
        object_path, meta_path = await asyncio.to_thread(self._paths, key)
        return await asyncio.to_thread(self._delete_sync, object_path, meta_path)

    async def exists(self, key: str) -> bool:
        object_path, _ = await asyncio.to_thread(self._paths, key)
        return await asyncio.to_thread(object_path.is_file)

    async def list(self, prefix: str = "") -> AsyncIterator[ObjectMetadata]:
        validate_prefix(prefix)
        for key in await asyncio.to_thread(self._list_keys_sync, prefix):
            try:
                yield await self.get_metadata(key)
            except StorageObjectNotFoundError:
                continue  # deleted between the walk and now

    async def get_metadata(self, key: str) -> ObjectMetadata:
        object_path, meta_path = await asyncio.to_thread(self._paths, key)
        return await asyncio.to_thread(self._metadata_sync, key, object_path, meta_path)


__all__ = ["FileSystemStorage"]
