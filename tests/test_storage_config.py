from pathlib import Path

import pytest
from pydantic import ValidationError

from common.config import AppSettings
from common.schemas.storage import (
    AzureBlobAuthMode,
    AzureBlobStorageSettings,
    StorageProvider,
    StorageSettings,
)
from common.storage.azure_blob import AzureBlobStorage
from common.storage.factory import create_storage_service
from common.storage.filesystem import FileSystemStorage

SECRET = "DefaultEndpointsProtocol=https;AccountName=acct;AccountKey=c2VjcmV0LWtleQ=="


@pytest.fixture(autouse=True)
def _clear_storage_env(monkeypatch):
    for name in (
        "STORAGE_PROVIDER",
        "STORAGE_FILESYSTEM_ROOT",
        "TEST_STORAGE_CONNECTION",
        "TEST_REDIS_CONNECTION",
        "REDIS_CONNECTION_STRING",
    ):
        monkeypatch.delenv(name, raising=False)


def _write_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(body)
    return path


def test_storage_defaults_to_the_filesystem_provider():
    settings = AppSettings()

    assert settings.storage.provider == StorageProvider.FILESYSTEM
    assert settings.storage.filesystem.root == Path("data/storage")
    assert settings.storage.azure_blob is None


def test_storage_section_is_read_from_yaml(tmp_path):
    path = _write_config(
        tmp_path,
        """
models: []
storage:
  provider: filesystem
  filesystem:
    root: /srv/objects
""",
    )

    settings = AppSettings(path)

    assert settings.storage.filesystem.root == Path("/srv/objects")


def test_a_config_file_without_a_storage_section_uses_defaults(tmp_path):
    settings = AppSettings(_write_config(tmp_path, "models: []\n"))

    assert settings.storage == StorageSettings()


def test_redis_connection_string_is_resolved_from_yaml_env_reference(tmp_path, monkeypatch):
    secret = "redis://:not-for-logs@redis.internal:6379/2"
    monkeypatch.setenv("TEST_REDIS_CONNECTION", secret)
    path = _write_config(
        tmp_path,
        "redis:\n  connection_string_env: TEST_REDIS_CONNECTION\n",
    )

    settings = AppSettings(path)

    assert settings.redis.is_configured
    assert settings.redis.connection_string.get_secret_value() == secret
    assert secret not in repr(settings.redis)
    assert secret not in settings.redis.model_dump_json()


def test_missing_optional_redis_secret_disables_the_cache(tmp_path):
    settings = AppSettings(
        _write_config(
            tmp_path,
            "redis:\n  connection_string_env: TEST_REDIS_CONNECTION\n",
        )
    )

    assert not settings.redis.is_configured


def test_environment_overrides_provider_and_filesystem_root(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_FILESYSTEM_ROOT", "/data/storage")
    path = _write_config(tmp_path, "storage:\n  filesystem:\n    root: data/storage\n")

    settings = AppSettings(path)

    assert settings.storage.filesystem.root == Path("/data/storage")

    monkeypatch.setenv("STORAGE_PROVIDER", "azure_blob")
    with pytest.raises(ValidationError, match="azure_blob settings are required"):
        AppSettings(path)


def test_connection_string_is_resolved_from_the_named_environment_variable(monkeypatch):
    monkeypatch.setenv("TEST_STORAGE_CONNECTION", SECRET)

    settings = AzureBlobStorageSettings.model_validate(
        {
            "auth_mode": "connection_string",
            "connection_string_env": "TEST_STORAGE_CONNECTION",
            "container": "files",
        }
    )

    assert settings.connection_string.get_secret_value() == SECRET


def test_the_connection_string_never_appears_in_reprs(monkeypatch):
    monkeypatch.setenv("TEST_STORAGE_CONNECTION", SECRET)
    settings = StorageSettings.model_validate(
        {
            "provider": "azure_blob",
            "azure_blob": {
                "auth_mode": "connection_string",
                "connection_string_env": "TEST_STORAGE_CONNECTION",
                "container": "files",
            },
        }
    )

    storage = create_storage_service(settings)

    for text in (repr(settings), str(settings), repr(storage), settings.model_dump_json()):
        assert "c2VjcmV0LWtleQ" not in text


def test_validation_errors_do_not_echo_the_connection_string():
    # managed_identity without account_url fails even though a secret is present.
    with pytest.raises(ValidationError) as error:
        StorageSettings.model_validate(
            {
                "provider": "azure_blob",
                "azure_blob": {"auth_mode": "managed_identity", "connection_string": SECRET},
            }
        )

    assert "account_url is required" in str(error.value)
    assert "c2VjcmV0LWtleQ" not in str(error.value)


def test_connection_string_mode_requires_the_secret():
    with pytest.raises(ValidationError, match="connection_string is required"):
        StorageSettings.model_validate(
            {
                "provider": "azure_blob",
                "azure_blob": {
                    "auth_mode": "connection_string",
                    "connection_string_env": "TEST_STORAGE_CONNECTION",  # unset
                },
            }
        )


def test_an_unselected_azure_section_is_not_validated():
    settings = StorageSettings.model_validate(
        {
            "provider": "filesystem",
            "azure_blob": {
                "auth_mode": "connection_string",
                "connection_string_env": "TEST_STORAGE_CONNECTION",  # unset
            },
        }
    )

    assert settings.provider == StorageProvider.FILESYSTEM


def test_factory_builds_the_filesystem_provider(tmp_path):
    settings = StorageSettings(filesystem={"root": tmp_path})

    assert isinstance(create_storage_service(settings), FileSystemStorage)


async def test_factory_builds_the_azure_provider_for_both_auth_modes():
    connection = AzureBlobStorageSettings(
        auth_mode=AzureBlobAuthMode.CONNECTION_STRING, connection_string=SECRET
    )
    managed = AzureBlobStorageSettings(
        auth_mode=AzureBlobAuthMode.MANAGED_IDENTITY,
        account_url="https://acct.blob.core.windows.net",
        managed_identity_client_id="00000000-0000-0000-0000-000000000001",
    )

    for azure_blob in (connection, managed):
        storage = create_storage_service(
            StorageSettings(provider=StorageProvider.AZURE_BLOB, azure_blob=azure_blob)
        )
        assert isinstance(storage, AzureBlobStorage)
        await storage.aclose()
