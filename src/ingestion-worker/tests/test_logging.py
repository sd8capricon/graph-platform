import logging
from pathlib import Path

import pytest
from celery import signals
from pydantic import ValidationError

import ingestion_worker.celery_app  # noqa: F401 - connects the setup_logging receiver
from ingestion_worker.config import CONFIG_PATH_ENV, load_worker_settings


@pytest.fixture(autouse=True)
def _restore_root_logger():
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    for handler in root.handlers:
        if handler not in handlers:
            handler.close()
    root.handlers[:] = handlers
    root.setLevel(level)


def _write_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(body)
    return path


def test_reads_the_worker_section(tmp_path):
    path = _write_config(
        tmp_path,
        """
ingestion_worker:
  logging:
    log_level: debug
    log_output: file
    log_file_path: logs/worker.log
agent_runtime:
  logging:
    log_level: ERROR
""",
    )

    logging_settings = load_worker_settings(path).logging

    assert logging_settings.log_level == "DEBUG"
    assert logging_settings.log_output == "file"
    assert logging_settings.log_file_path == Path("logs/worker.log")


def test_missing_section_uses_defaults(tmp_path):
    path = _write_config(tmp_path, "models: []\n")

    logging_settings = load_worker_settings(path).logging

    assert logging_settings.log_level == "INFO"
    assert logging_settings.log_output == "stdout"


def test_unknown_worker_key_fails(tmp_path):
    path = _write_config(tmp_path, "ingestion_worker:\n  loging: {}\n")

    with pytest.raises(ValidationError):
        load_worker_settings(path)


def test_honors_config_path_env(tmp_path, monkeypatch):
    path = _write_config(tmp_path, "ingestion_worker:\n  logging:\n    log_level: ERROR\n")
    monkeypatch.setenv(CONFIG_PATH_ENV, str(path))

    assert load_worker_settings().logging.log_level == "ERROR"


def test_celery_setup_logging_applies_yaml(tmp_path, monkeypatch):
    log_file = tmp_path / "worker.log"
    path = _write_config(
        tmp_path,
        f"""
ingestion_worker:
  logging:
    log_level: WARNING
    log_output: file
    log_file_path: {log_file}
""",
    )
    monkeypatch.setenv(CONFIG_PATH_ENV, str(path))

    # Celery sends this at worker/Beat startup; our receiver ignores `loglevel`.
    signals.setup_logging.send(sender=None, loglevel="INFO")
    logging.getLogger("ingestion_worker.test").warning("stage failed")

    root = logging.getLogger()
    assert root.level == logging.WARNING
    for handler in root.handlers:
        handler.flush()
    assert "ingestion_worker.test: stage failed" in log_file.read_text()

