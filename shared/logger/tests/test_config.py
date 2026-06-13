"""Tests for shared.logger.config — configure_logging and get_logger."""

from __future__ import annotations

import json
import logging
from typing import Iterator

import pytest
import structlog

from shared.logger.config import configure_logging, get_logger


@pytest.fixture(autouse=True)
def _reset_structlog_between_tests() -> Iterator[None]:
    """Reset structlog to defaults so tests don't bleed configuration."""
    structlog.reset_defaults()
    root = logging.getLogger()
    root.handlers = []
    root.setLevel(logging.WARNING)
    yield
    structlog.reset_defaults()
    root.handlers = []
    root.setLevel(logging.WARNING)


class TestGetLogger:
    def test_returns_a_logger(self) -> None:
        configure_logging(env="dev", log_level="INFO")
        logger = get_logger("test")
        assert logger is not None

    def test_bind_returns_a_logger_too(self) -> None:
        configure_logging(env="dev", log_level="INFO")
        logger = get_logger("test")
        bound = logger.bind(user_id="abc")
        assert bound is not None

    def test_safe_to_call_before_configure(self) -> None:
        # The lazy proxy means get_logger before configure must not crash
        logger = get_logger("test")
        assert logger is not None


class TestConfigureLogging:
    def test_idempotent(self) -> None:
        configure_logging(env="dev", log_level="INFO")
        configure_logging(env="prod", log_level="DEBUG")
        # No exception; the second config wins
        assert logging.getLogger().level == logging.DEBUG

    def test_log_level_respected(self) -> None:
        configure_logging(env="dev", log_level="WARNING")
        assert logging.getLogger().level == logging.WARNING

    def test_log_level_default_is_info(self) -> None:
        configure_logging(env="dev")
        assert logging.getLogger().level == logging.INFO

    def test_unknown_log_level_falls_back_to_info(self) -> None:
        configure_logging(env="dev", log_level="NOT_A_LEVEL")
        assert logging.getLogger().level == logging.INFO

    def test_noisy_libraries_quieted(self) -> None:
        configure_logging(env="dev", log_level="DEBUG")
        # urllib3 and asyncio should be set to WARNING regardless of root level
        assert logging.getLogger("urllib3").level == logging.WARNING
        assert logging.getLogger("asyncio").level == logging.WARNING


class TestProdJSONOutput:
    def test_emits_valid_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        configure_logging(env="prod", log_level="INFO")
        logger = get_logger("test")
        logger.info("user.created", user_id="42", email="x@example.com")

        captured = capsys.readouterr()
        # Take the last non-empty line in case other tests emitted things
        lines = [line for line in captured.out.splitlines() if line.strip()]
        assert lines, "Expected at least one log line"
        parsed = json.loads(lines[-1])

        assert parsed["event"] == "user.created"
        assert parsed["user_id"] == "42"
        assert parsed["email"] == "x@example.com"
        assert parsed["level"] == "info"
        assert "timestamp" in parsed

    def test_scrubs_sensitive_keys_in_prod(self, capsys: pytest.CaptureFixture[str]) -> None:
        configure_logging(env="prod", log_level="INFO")
        logger = get_logger("test")
        logger.info("login.attempt", email="x@example.com", password="secret123")

        captured = capsys.readouterr()
        lines = [line for line in captured.out.splitlines() if line.strip()]
        parsed = json.loads(lines[-1])

        assert parsed["email"] == "x@example.com"
        assert parsed["password"] == "[REDACTED]"
        assert "secret123" not in captured.out


class TestDevConsoleOutput:
    def test_emits_console_format(self, capsys: pytest.CaptureFixture[str]) -> None:
        configure_logging(env="ci", log_level="INFO")  # ci => colors off, easier to assert
        logger = get_logger("test")
        logger.info("user.created", user_id="42")

        captured = capsys.readouterr()
        # Console renderer uses key=value format (not JSON)
        assert "user.created" in captured.out
        assert "user_id" in captured.out
        # Should NOT be valid JSON
        with pytest.raises(json.JSONDecodeError):
            json.loads(captured.out.strip().split("\n")[-1])

    def test_scrubs_sensitive_keys_in_dev_too(self, capsys: pytest.CaptureFixture[str]) -> None:
        configure_logging(env="ci", log_level="INFO")
        logger = get_logger("test")
        logger.info("login.attempt", password="secret123")

        captured = capsys.readouterr()
        assert "[REDACTED]" in captured.out
        assert "secret123" not in captured.out


class TestLogLevelFiltering:
    def test_debug_filtered_at_info_level(self, capsys: pytest.CaptureFixture[str]) -> None:
        configure_logging(env="prod", log_level="INFO")
        logger = get_logger("test")
        logger.debug("debug.event", x=1)
        logger.info("info.event", x=2)

        captured = capsys.readouterr()
        assert "debug.event" not in captured.out
        assert "info.event" in captured.out

    def test_debug_emitted_at_debug_level(self, capsys: pytest.CaptureFixture[str]) -> None:
        configure_logging(env="prod", log_level="DEBUG")
        logger = get_logger("test")
        logger.debug("debug.event", x=1)

        captured = capsys.readouterr()
        assert "debug.event" in captured.out
