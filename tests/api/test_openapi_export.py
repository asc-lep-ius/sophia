"""Deterministic OpenAPI export tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]
EXPORT_SCRIPT = REPO_ROOT / "scripts" / "export_openapi.py"
HTTP_METHODS = {"delete", "get", "patch", "post", "put"}


def test_openapi_export_is_deterministic(tmp_path: Path) -> None:
    first_output = tmp_path / "first.json"
    second_output = tmp_path / "second.json"

    first_result = _run_export("--output", str(first_output))
    second_result = _run_export("--output", str(second_output))

    assert first_result.returncode == 0, first_result.stderr
    assert second_result.returncode == 0, second_result.stderr
    assert first_output.read_bytes() == second_output.read_bytes()


def test_openapi_check_fails_on_drift_and_passes_after_regeneration(tmp_path: Path) -> None:
    output = tmp_path / "openapi.json"

    write_result = _run_export("--output", str(output))
    assert write_result.returncode == 0, write_result.stderr

    output.write_text('{"drifted": true}\n')
    drift_result = _run_export("--output", str(output), "--check")
    assert drift_result.returncode == 1
    assert "OpenAPI output is out of date" in drift_result.stderr

    rewrite_result = _run_export("--output", str(output))
    assert rewrite_result.returncode == 0, rewrite_result.stderr

    check_result = _run_export("--output", str(output), "--check")
    assert check_result.returncode == 0, check_result.stderr


def test_openapi_export_declares_request_id_response_headers(tmp_path: Path) -> None:
    output = tmp_path / "openapi.json"
    result = _run_export("--output", str(output))
    assert result.returncode == 0, result.stderr

    document = json.loads(output.read_text())
    response_headers = [
        response.get("headers", {})
        for path_item in document.get("paths", {}).values()
        if isinstance(path_item, dict)
        for method, operation in path_item.items()
        if method in HTTP_METHODS and isinstance(operation, dict)
        for response in operation.get("responses", {}).values()
        if isinstance(response, dict)
    ]

    assert response_headers
    assert all("X-Request-ID" in headers for headers in response_headers)


def _run_export(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(EXPORT_SCRIPT), *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_status_descriptions_do_not_depend_on_the_interpreter() -> None:
    """3.13 renamed 422 to the RFC 9110 wording, so the raw phrase is not portable."""
    document = json.loads(_render_document())
    descriptions = {
        response.get("description")
        for path_item in document["paths"].values()
        for method, operation in path_item.items()
        if method in HTTP_METHODS
        for status_code, response in operation.get("responses", {}).items()
        if status_code == "422"
    }

    # "Validation Error" is FastAPI's own wording for the automatic 422 and is
    # portable; only the HTTPStatus-derived phrase moves between interpreters.
    assert "Unprocessable Entity" not in descriptions
    assert "Unprocessable Content" in descriptions


def test_canonicalisation_rewrites_the_pre_3_13_phrase() -> None:
    from scripts.export_openapi import _canonicalize_status_descriptions

    document: dict[str, object] = {
        "paths": {
            "/api/search": {
                "post": {
                    "responses": {
                        "422": {"description": "Unprocessable Entity"},
                        "404": {"description": "Not Found"},
                    },
                },
            },
        },
    }

    _canonicalize_status_descriptions(document)

    responses = document["paths"]["/api/search"]["post"]["responses"]  # type: ignore[index]
    assert responses["422"]["description"] == "Unprocessable Content"
    assert responses["404"]["description"] == "Not Found"


def _render_document() -> bytes:
    from scripts.export_openapi import render_openapi

    return render_openapi()
