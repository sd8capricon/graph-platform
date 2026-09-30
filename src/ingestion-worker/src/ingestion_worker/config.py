"""Ingestion worker configuration.

The worker resolves its embedding/chat provider the same way the API and the
agent runtime do - from `common.config.settings.models` - but selects by the
`index_job.embedding_model_id` the API stamped onto the job (ADR-0001/0002
provenance), not by "first embedding model".
"""

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from common.config import DEFAULT_CONFIG_PATH, load_config, settings
from common.logging_setup import configure_logging
from common.schemas.logging import LoggingSettings
from common.schemas.model import Model, ModelType
from ingestion_worker.errors import NonRetryableIngestionError

RABBITMQ_URL_ENV = "RABBITMQ_URL"
DEFAULT_RABBITMQ_URL = "amqp://guest:guest@localhost:5672//"

CONFIG_PATH_ENV = "INGESTION_CONFIG_PATH"

WORKER_CONFIG_SECTION = "ingestion_worker"
"""Top-level YAML key holding this service's own settings (e.g. `logging`)."""


class IngestionWorkerSettings(BaseModel):
    """The worker's own `ingestion_worker` section of the YAML config.

    Kept out of `common.config.AppSettings` so shared settings stay unaware of
    per-service sections; each service validates only its own.
    """

    model_config = ConfigDict(extra="forbid")

    logging: LoggingSettings = Field(default_factory=LoggingSettings)


def worker_config_path() -> Path:
    """`INGESTION_CONFIG_PATH` when set, otherwise the shared default path."""
    return Path(os.environ.get(CONFIG_PATH_ENV) or DEFAULT_CONFIG_PATH)


def load_worker_config() -> None:
    """Load the provider config into the shared `settings` singleton.

    Uses `INGESTION_CONFIG_PATH` when set, otherwise the shared default
    (`configs/local.yaml` relative to the working directory). Safe to call more
    than once; it updates `settings` in place.
    """
    load_config(worker_config_path())


def load_worker_settings(path: str | Path | None = None) -> IngestionWorkerSettings:
    """Read and validate the `ingestion_worker` section of the YAML config.

    Args:
        path: Config file; defaults to `worker_config_path()`.

    Returns:
        The validated section, or all defaults when the section is absent.
    """
    loaded = yaml.safe_load(Path(path or worker_config_path()).read_text()) or {}
    return IngestionWorkerSettings.model_validate(loaded.get(WORKER_CONFIG_SECTION) or {})


def configure_worker_logging(path: str | Path | None = None) -> None:
    """Apply the worker's `ingestion_worker.logging` section to the root logger."""
    configure_logging(load_worker_settings(path).logging)


def rabbitmq_url() -> str:
    """Broker URL for Celery, from `RABBITMQ_URL` (with a local default)."""
    return os.environ.get(RABBITMQ_URL_ENV, DEFAULT_RABBITMQ_URL)


def embedding_model_for_job(embedding_model_id: str | None) -> Model:
    """Resolve the embedding provider for a job.

    The API stamps the organization's active embedding model onto the job at
    publish time (ADR-0001/0002 provenance). There is no fallback to "first
    embedding model": vectors from a different model than the organization's
    active one could not be searched with it.

    Raises:
        NonRetryableIngestionError: If the job recorded no embedding model (the
            organization has none set), the id is not in the worker's
            configuration, or the configured model is not embedding-capable.
    """
    if not embedding_model_id:
        raise NonRetryableIngestionError(
            "organization has no embedding model set; "
            "configure an active embedding model before indexing"
        )
    for model in settings.models:
        if model.id == embedding_model_id:
            if ModelType.EMBEDDING not in model.type:
                raise NonRetryableIngestionError(
                    f"model {embedding_model_id!r} is not an embedding model"
                )
            return model
    raise NonRetryableIngestionError(
        f"embedding model {embedding_model_id!r} is not configured on the worker"
    )


__all__ = [
    "rabbitmq_url",
    "embedding_model_for_job",
    "load_worker_config",
    "load_worker_settings",
    "configure_worker_logging",
    "worker_config_path",
    "IngestionWorkerSettings",
    "WORKER_CONFIG_SECTION",
    "RABBITMQ_URL_ENV",
    "DEFAULT_RABBITMQ_URL",
    "CONFIG_PATH_ENV",
]