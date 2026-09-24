"""Ingestion worker configuration.

The worker resolves its embedding/chat provider the same way the API and the
agent runtime do - from `common.config.settings.models` - but selects by the
`index_job.embedding_model_id` the API stamped onto the job (ADR-0001/0002
provenance), not by "first embedding model".
"""

import os

from common.config import load_config, settings
from common.schemas.model import Model, ModelType

RABBITMQ_URL_ENV = "RABBITMQ_URL"
DEFAULT_RABBITMQ_URL = "amqp://guest:guest@localhost:5672//"

CONFIG_PATH_ENV = "INGESTION_CONFIG_PATH"


def load_worker_config() -> None:
    """Load the provider config into the shared `settings` singleton.

    Uses `INGESTION_CONFIG_PATH` when set, otherwise the shared default
    (`configs/local.yaml` relative to the working directory). Safe to call more
    than once; it updates `settings` in place.
    """
    path = os.environ.get(CONFIG_PATH_ENV)
    if path:
        load_config(path)
    else:
        load_config()


def rabbitmq_url() -> str:
    """Broker URL for Celery, from `RABBITMQ_URL` (with a local default)."""
    return os.environ.get(RABBITMQ_URL_ENV, DEFAULT_RABBITMQ_URL)


def embedding_model_for_job(embedding_model_id: str | None) -> Model | None:
    """Resolve the embedding provider for a job.

    Prefers the job's recorded `embedding_model_id`; falls back to the first
    embedding-capable model when the job did not record one (a legacy row).
    Returns None when no embedding provider is configured, in which case the
    side-table writes store rows without vectors.
    """
    if embedding_model_id:
        for model in settings.models:
            if model.id == embedding_model_id:
                return model
    return next((m for m in settings.models if ModelType.EMBEDDING in m.type), None)


__all__ = [
    "rabbitmq_url",
    "embedding_model_for_job",
    "load_worker_config",
    "RABBITMQ_URL_ENV",
    "DEFAULT_RABBITMQ_URL",
    "CONFIG_PATH_ENV",
]