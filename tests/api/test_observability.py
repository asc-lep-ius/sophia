"""Observability configuration tests."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import structlog

from sophia.api import app as api_app_module
from sophia.api import create_api_app
from sophia.config import Settings
from sophia.infra.logging import setup_logging

if TYPE_CHECKING:
    from pytest import CaptureFixture, MonkeyPatch


def test_sentry_is_not_initialized_without_dsn(monkeypatch: MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def capture_init(**kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(api_app_module.sentry_sdk, "init", capture_init)

    create_api_app(Settings(sentry_dsn=""))

    assert calls == []


def test_sentry_initialization_uses_privacy_safe_options(monkeypatch: MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def capture_init(**kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(api_app_module.sentry_sdk, "init", capture_init)

    create_api_app(
        Settings(
            sentry_dsn="https://public@example.test/1",
            sentry_release="sophia@abc123",
            sentry_environment="test",
            sentry_traces_sample_rate=0.25,
        )
    )

    assert len(calls) == 1
    options = calls[0]
    assert options["dsn"] == "https://public@example.test/1"
    assert options["release"] == "sophia@abc123"
    assert options["environment"] == "test"
    assert options["traces_sample_rate"] == 0.25
    assert options["send_default_pii"] is False
    assert options["include_local_variables"] is False
    assert callable(options["before_send"])


def test_sentry_before_send_scrubs_sensitive_request_data(monkeypatch: MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def capture_init(**kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(api_app_module.sentry_sdk, "init", capture_init)
    create_api_app(Settings(sentry_dsn="https://public@example.test/1"))
    before_send = calls[0]["before_send"]

    scrubbed = before_send(
        {
            "request": {
                "headers": {
                    "Authorization": "Bearer secret",
                    "Cookie": "session_id=secret",
                    "X-Request-ID": "req-safe",
                },
                "cookies": {"session_id": "secret"},
                "query_string": "prompt=secret&email=learner@example.test",
                "data": {"prompt": "secret", "content": "secret"},
            },
            "extra": {
                "learner_id": "learner-123",
                "safe_count": 2,
            },
        },
        {},
    )

    assert scrubbed["request"] == {
        "headers": {
            "Authorization": "[redacted]",
            "Cookie": "[redacted]",
            "X-Request-ID": "req-safe",
        }
    }
    assert scrubbed["extra"] == {"learner_id": "[redacted]", "safe_count": 2}


def test_sentry_before_send_drops_exception_frame_vars(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def capture_init(**kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(api_app_module.sentry_sdk, "init", capture_init)
    create_api_app(Settings(sentry_dsn="https://public@example.test/1"))
    before_send = calls[0]["before_send"]

    scrubbed = before_send(
        {
            "exception": {
                "values": [
                    {
                        "type": "RuntimeError",
                        "stacktrace": {
                            "frames": [
                                {
                                    "filename": "study.py",
                                    "function": "grade_answer",
                                    "vars": {
                                        "prompt": "hidden prompt",
                                        "session_id": "session-secret",
                                        "safe_count": 2,
                                    },
                                }
                            ]
                        },
                    }
                ]
            }
        },
        {},
    )

    frame = scrubbed["exception"]["values"][0]["stacktrace"]["frames"][0]
    assert frame == {"filename": "study.py", "function": "grade_answer"}


def test_sentry_before_send_scrubs_sensitive_breadcrumbs(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def capture_init(**kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(api_app_module.sentry_sdk, "init", capture_init)
    create_api_app(Settings(sentry_dsn="https://public@example.test/1"))
    before_send = calls[0]["before_send"]

    scrubbed = before_send(
        {
            "breadcrumbs": {
                "values": [
                    {
                        "type": "default",
                        "message": "submitting prompt=hidden prompt",
                        "data": {
                            "authorization": "Bearer secret-token",
                            "safe_count": 2,
                            "nested": {
                                "session_id": "session-secret",
                                "safe": "ok",
                            },
                        },
                    },
                    {
                        "type": "default",
                        "message": "route resolved",
                        "data": {"safe": "ok"},
                    },
                ]
            }
        },
        {},
    )

    assert scrubbed["breadcrumbs"] == {
        "values": [
            {
                "type": "default",
                "message": "[redacted]",
                "data": {
                    "authorization": "[redacted]",
                    "safe_count": 2,
                    "nested": {"session_id": "[redacted]", "safe": "ok"},
                },
            },
            {
                "type": "default",
                "message": "route resolved",
                "data": {"safe": "ok"},
            },
        ]
    }


def test_json_logging_includes_request_id_and_redacts_sensitive_fields(
    capsys: CaptureFixture[str],
) -> None:
    setup_logging(debug=False, json_logs=True, service_name="api")
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id="req-log")

    structlog.get_logger().info(
        "study.event",
        authorization="Bearer secret",
        session_id="session-secret",
        prompt="hidden prompt",
        content_text="hidden content",
        safe_count=1,
    )

    record = json.loads(capsys.readouterr().out)
    assert record["event"] == "study.event"
    assert record["service"] == "api"
    assert record["request_id"] == "req-log"
    assert record["safe_count"] == 1
    assert record["authorization"] == "[redacted]"
    assert record["session_id"] == "[redacted]"
    assert record["prompt"] == "[redacted]"
    assert record["content_text"] == "[redacted]"
    structlog.contextvars.clear_contextvars()


def test_json_logging_recursively_redacts_nested_payload_values(
    capsys: CaptureFixture[str],
) -> None:
    setup_logging(debug=False, json_logs=True, service_name="api")

    structlog.get_logger().info(
        "study.payload",
        payload={
            "prompt": "hidden prompt",
            "safe_count": 2,
            "items": [
                {"content_text": "hidden content"},
                {"nested": {"prompt": "hidden nested prompt", "safe": "ok"}},
            ],
        },
    )

    record = json.loads(capsys.readouterr().out)

    assert record["payload"] == {
        "prompt": "[redacted]",
        "safe_count": 2,
        "items": [
            {"content_text": "[redacted]"},
            {"nested": {"prompt": "[redacted]", "safe": "ok"}},
        ],
    }
