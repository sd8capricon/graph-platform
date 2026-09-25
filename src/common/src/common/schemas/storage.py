import os
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

STORAGE_PROVIDER_ENV = "STORAGE_PROVIDER"
"""Environment variable overriding `StorageSettings.provider` (e.g. in a container)."""

STORAGE_FILESYSTEM_ROOT_ENV = "STORAGE_FILESYSTEM_ROOT"
"""Environment variable overriding `FileSystemStorageSettings.root`.

Lets a container point storage at a mounted volume (e.g. `/data/storage`) without
editing the YAML file baked into the image.
"""


class StorageProvider(str, Enum):
    """Enumeration of supported object storage providers.

    Attributes:
        FILESYSTEM: Objects live under a local (or volume-mounted) directory.
        AZURE_BLOB: Objects live in one Azure Blob Storage container.
    """

    FILESYSTEM = "filesystem"
    AZURE_BLOB = "azure_blob"


class AzureBlobAuthMode(str, Enum):
    """Enumeration of supported Azure Blob Storage authentication modes.

    Attributes:
        CONNECTION_STRING: Authenticate with a storage account connection string.
            Intended for development (including Azurite).
        MANAGED_IDENTITY: Authenticate with `DefaultAzureCredential` (managed
            identity in Azure, developer credentials locally). No secret is stored.
    """

    CONNECTION_STRING = "connection_string"
    MANAGED_IDENTITY = "managed_identity"


class FileSystemStorageSettings(BaseModel):
    """Configuration for `FileSystemStorage`.

    Attributes:
        root: Directory holding every stored object. Relative paths resolve
            against the working directory, like `DEFAULT_CONFIG_PATH`. In a
            container, point it at a mounted volume so objects survive restarts.
    """

    root: Path = Path("data/storage")


class AzureBlobStorageSettings(BaseModel):
    """Configuration for `AzureBlobStorage`.

    Attributes:
        auth_mode: How to authenticate: 'connection_string' or 'managed_identity'.
        account_url: Blob service endpoint (`https://<account>.blob.core.windows.net`),
            required for 'managed_identity'.
        container: Name of the container holding every stored object.
        managed_identity_client_id: Client id of a user-assigned managed identity.
            Omit to use the system-assigned identity / default credential chain.
        connection_string: Storage account connection string, required for
            'connection_string'. Never inlined in YAML - resolved from the
            environment variable named by `connection_string_env`. Stored as a
            SecretStr so it is masked in reprs/logs.
        create_container: Create the container on first use if it is missing.
            Convenient for development/Azurite; leave off in production, where
            the identity usually lacks container-management rights.
        max_block_size: Size in bytes of each block staged for a streamed upload.
            Bounds the memory a streamed upload holds at once.
        max_single_put_size: Largest `bytes` payload uploaded in one request;
            larger payloads are split into blocks by the SDK.
        max_concurrency: Parallel connections the SDK uses per transfer.
    """

    # Pydantic echoes the raw input into ValidationError messages by default,
    # which here would include the resolved connection string.
    model_config = ConfigDict(hide_input_in_errors=True)

    auth_mode: AzureBlobAuthMode = AzureBlobAuthMode.MANAGED_IDENTITY
    account_url: str | None = None
    container: str = "graph-platform"
    managed_identity_client_id: str | None = None
    connection_string: SecretStr | None = None
    create_container: bool = False
    max_block_size: int = Field(default=4 * 1024 * 1024, gt=0)
    max_single_put_size: int = Field(default=8 * 1024 * 1024, gt=0)
    max_concurrency: int = Field(default=4, gt=0)

    @model_validator(mode="before")
    @classmethod
    def resolve_connection_string_env(cls, data: Any) -> Any:
        """Resolve the `connection_string_env` config indirection into `connection_string`.

        Mirrors `Model.resolve_api_key_env`: config files name an environment
        variable rather than inlining the secret.

        Args:
            data: The raw data dictionary before model instantiation.

        Returns:
            The data dictionary with `connection_string_env` replaced by
            `connection_string`.
        """
        if isinstance(data, dict) and "connection_string_env" in data:
            data = dict(data)
            env_name = data.pop("connection_string_env")
            if env_name:
                data.setdefault("connection_string", os.environ.get(env_name))
        return data

    def ensure_credentials(self) -> None:
        """Ensure the settings the configured `auth_mode` needs are present.

        Not a validator: an `azure_blob` section may sit in the YAML file while
        `provider` is 'filesystem' (with its secret's environment variable unset),
        so `StorageSettings` only calls this for the selected provider, and
        `AzureBlobStorage` calls it again on construction. Error messages name
        the missing setting only - never a value.

        Raises:
            ValueError: If a setting required by `auth_mode` is missing.
        """
        if not self.container:
            raise ValueError("azure_blob.container is required")
        if self.auth_mode == AzureBlobAuthMode.CONNECTION_STRING and not (
            self.connection_string and self.connection_string.get_secret_value()
        ):
            raise ValueError(
                "azure_blob.connection_string is required when auth_mode is "
                "'connection_string' (set the variable named by connection_string_env)"
            )
        if self.auth_mode == AzureBlobAuthMode.MANAGED_IDENTITY and not self.account_url:
            raise ValueError(
                "azure_blob.account_url is required when auth_mode is 'managed_identity'"
            )


class StorageSettings(BaseModel):
    """Object storage configuration (the `storage:` section of `configs/local.yaml`).

    Attributes:
        provider: Which provider `create_storage_service()` builds.
        filesystem: Settings for the 'filesystem' provider.
        azure_blob: Settings for the 'azure_blob' provider. Only validated when
            it is the selected provider, so a filesystem deployment needs no
            Azure configuration at all.
    """

    model_config = ConfigDict(hide_input_in_errors=True)

    provider: StorageProvider = StorageProvider.FILESYSTEM
    filesystem: FileSystemStorageSettings = Field(default_factory=FileSystemStorageSettings)
    azure_blob: AzureBlobStorageSettings | None = None

    @model_validator(mode="before")
    @classmethod
    def apply_environment_overrides(cls, data: Any) -> Any:
        """Apply `STORAGE_PROVIDER` / `STORAGE_FILESYSTEM_ROOT` over the YAML values.

        These are deployment-shaped settings (a container picks its provider and
        volume path), so the environment wins over the file.

        Args:
            data: The raw data dictionary before model instantiation.

        Returns:
            The data dictionary with any environment overrides applied.
        """
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if provider := os.environ.get(STORAGE_PROVIDER_ENV):
            data["provider"] = provider
        if root := os.environ.get(STORAGE_FILESYSTEM_ROOT_ENV):
            filesystem = data.get("filesystem") or {}
            if isinstance(filesystem, BaseModel):
                filesystem = filesystem.model_dump()
            data["filesystem"] = {**filesystem, "root": root}
        return data

    @model_validator(mode="after")
    def ensure_selected_provider_is_configured(self) -> "StorageSettings":
        """Ensure the selected provider has its settings section.

        Returns:
            The validated settings instance.

        Raises:
            ValueError: If `provider` is 'azure_blob' but `azure_blob` is missing
                or lacks what its `auth_mode` needs.
        """
        if self.provider == StorageProvider.AZURE_BLOB:
            if self.azure_blob is None:
                raise ValueError("azure_blob settings are required when provider is 'azure_blob'")
            self.azure_blob.ensure_credentials()
        return self


__all__ = [
    "AzureBlobAuthMode",
    "AzureBlobStorageSettings",
    "FileSystemStorageSettings",
    "STORAGE_FILESYSTEM_ROOT_ENV",
    "STORAGE_PROVIDER_ENV",
    "StorageProvider",
    "StorageSettings",
]
