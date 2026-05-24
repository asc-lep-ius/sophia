"""Export the FastAPI OpenAPI document deterministically."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sophia.api import create_api_app

DEFAULT_OUTPUT = Path("frontend/src/lib/api/openapi.json")
HTTP_METHODS = frozenset({"delete", "get", "patch", "post", "put"})
REQUEST_ID_HEADER_NAME = "X-Request-ID"
REQUEST_ID_HEADER_SCHEMA = {
    "description": "Request correlation identifier.",
    "schema": {"type": "string"},
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"OpenAPI output path. Defaults to {DEFAULT_OUTPUT}.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if the output path does not already match the generated document.",
    )
    args = parser.parse_args(argv)

    output = args.output
    content = render_openapi()
    if args.check:
        return _check_output(output, content)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(content)
    return 0


def render_openapi() -> bytes:
    document = create_api_app().openapi()
    _add_response_header_contracts(document)
    sorted_document = _sort_openapi_document(document)
    return f"{json.dumps(sorted_document, sort_keys=True, indent=2)}\n".encode()


def _add_response_header_contracts(document: dict[str, Any]) -> None:
    paths = document.get("paths")
    if not isinstance(paths, dict):
        return

    for path_item in paths.values():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            responses = operation.get("responses")
            if not isinstance(responses, dict):
                continue
            for response in responses.values():
                if not isinstance(response, dict) or "$ref" in response:
                    continue
                headers = response.setdefault("headers", {})
                if isinstance(headers, dict):
                    headers.setdefault(REQUEST_ID_HEADER_NAME, REQUEST_ID_HEADER_SCHEMA.copy())


def _sort_openapi_document(document: dict[str, Any]) -> dict[str, Any]:
    paths = document.get("paths")
    if isinstance(paths, dict):
        document["paths"] = {path: paths[path] for path in sorted(paths)}

    tags = document.get("tags")
    if isinstance(tags, list):
        document["tags"] = sorted(tags, key=_tag_sort_key)

    components = document.get("components")
    if isinstance(components, dict):
        schemas = components.get("schemas")
        if isinstance(schemas, dict):
            components["schemas"] = {name: schemas[name] for name in sorted(schemas)}

    return document


def _tag_sort_key(tag: object) -> str:
    if isinstance(tag, dict):
        name = tag.get("name")
        if isinstance(name, str):
            return name
    return str(tag)


def _check_output(output: Path, expected_content: bytes) -> int:
    try:
        actual_content = output.read_bytes()
    except FileNotFoundError:
        sys.stderr.write(f"OpenAPI output is missing: {output}\n")
        return 1

    if actual_content != expected_content:
        sys.stderr.write("OpenAPI output is out of date. Run `make openapi` to regenerate it.\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
