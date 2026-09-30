import logging
import sys

import pytest
from pydantic import ValidationError

from common.logging_setup import configure_logging
from common.schemas.logging import LoggingSettings


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


def test_blank_values_use_defaults():
    settings = LoggingSettings(log_level="", log_output="  ", log_file_path="")

    assert settings.log_level == "INFO"
    assert settings.log_output == "stdout"
    assert settings.log_file_path is None


def test_choices_are_case_insensitive():
    settings = LoggingSettings(log_level=" debug ", log_output="STDOUT")

    assert settings.log_level == "DEBUG"
    assert settings.log_output == "stdout"


@pytest.mark.parametrize(
    "data",
    [
        {"log_level": "verbose"},
        {"log_output": "syslog"},
        {"log_levl": "INFO"},
        {"log_output": "file"},
        {"log_output": "file", "log_file_path": ""},
    ],
)
def test_invalid_settings_fail(data):
    with pytest.raises(ValidationError):
        LoggingSettings(**data)


def test_configure_stdout_sets_one_root_handler():
    settings = LoggingSettings(log_level="WARNING")

    configure_logging(settings)
    configure_logging(settings)

    root = logging.getLogger()
    assert root.level == logging.WARNING
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0], logging.StreamHandler)
    assert root.handlers[0].stream is sys.stdout


def test_configure_file_creates_parent_and_writes(tmp_path):
    path = tmp_path / "logs" / "worker.log"

    configure_logging(LoggingSettings(log_output="file", log_file_path=str(path)))
    logging.getLogger("some.module").info("hello from the worker")
    for handler in logging.getLogger().handlers:
        handler.flush()

    text = path.read_text()
    assert "INFO" in text
    assert "some.module: hello from the worker" in text


def test_existing_module_loggers_stay_enabled():
    module_logger = logging.getLogger("already.imported")

    configure_logging(LoggingSettings())

    assert not module_logger.disabled
