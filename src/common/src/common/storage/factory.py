"""Build the configured `StorageService`."""

from common.schemas.storage import StorageProvider, StorageSettings
from common.storage.base import StorageService


def create_storage_service(settings: StorageSettings) -> StorageService:
    """Build the `StorageService` selected by `settings.provider`.

    The single place a provider is chosen: business code takes a
    `StorageService` in its constructor (as `KnowledgeBaseService` takes its
    repository) and never imports a provider module itself. Providers are
    imported lazily so a filesystem deployment never loads the Azure SDK.

    Args:
        settings: Storage configuration, typically `common.config.settings.storage`.

    Returns:
        The configured provider. Close it with `aclose()` (or `async with`)
        when done.

    Raises:
        ValueError: If the selected provider's settings are incomplete.
    """
    if settings.provider == StorageProvider.AZURE_BLOB:
        from common.storage.azure_blob import AzureBlobStorage

        if settings.azure_blob is None:
            raise ValueError("azure_blob settings are required when provider is 'azure_blob'")
        return AzureBlobStorage(settings.azure_blob)

    from common.storage.filesystem import FileSystemStorage

    return FileSystemStorage(settings.filesystem.root)


__all__ = ["create_storage_service"]
