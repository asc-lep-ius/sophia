"""Source-agnostic vocabulary boundary for the public API contract.

The core contract must not name the systems Sophia happens to ingest from
today. Source-specific vocabulary is legal, but only under
``/api/integrations/{source}``, together with the schemas those endpoints
reach. Everything else stays content-agnostic: paths, operation ids, tags,
parameter names, schema names, property names, and enum values -- including
enums inlined into a property rather than named as their own schema.

Operation ids and tags matter as much as paths here, because they become the
function names and groupings of the generated TypeScript client.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from sophia.api import create_api_app

if TYPE_CHECKING:
    from collections.abc import Iterator

SOURCE_VOCABULARY = re.compile(
    r"moodle|tuwel|tiss|opencast|lecturetube|lecture|course|module|episode",
    re.IGNORECASE,
)
INTEGRATIONS_PREFIX = "/api/integrations/"
HTTP_METHODS = frozenset({"delete", "get", "patch", "post", "put"})
SCHEMA_REF_PREFIX = "#/components/schemas/"


def test_core_paths_use_no_source_vocabulary() -> None:
    document = create_api_app().openapi()

    offending_paths = sorted(
        path for path in _core_paths(document) if SOURCE_VOCABULARY.search(path)
    )

    assert offending_paths == []


def test_source_specific_paths_live_under_integrations() -> None:
    document = create_api_app().openapi()

    misplaced_paths = sorted(
        path
        for path in document["paths"]
        if SOURCE_VOCABULARY.search(path) and not path.startswith(INTEGRATIONS_PREFIX)
    )

    assert misplaced_paths == []


def test_core_schemas_use_no_source_vocabulary() -> None:
    document = create_api_app().openapi()

    # Guards the guard: an empty reachable set would make this vacuously true.
    assert "DeadlineResponse" in _reachable_schemas(document, integrations=False)
    assert _source_vocabulary_offenders(document) == []


def test_integration_schemas_may_use_source_vocabulary() -> None:
    """The exemption is real: TISS schemas keep their TISS names."""
    document = create_api_app().openapi()
    schemas = document["components"]["schemas"]

    integration_only = _reachable_schemas(document, integrations=True) - _reachable_schemas(
        document, integrations=False
    )

    assert "TissRegistrationTargetResponse" in integration_only
    assert "course_number" in schemas["TissRegistrationTargetResponse"]["properties"]


def test_boundary_check_flags_reintroduced_vocabulary() -> None:
    document: dict[str, Any] = {
        "paths": {
            "/api/learning-paths": {
                "get": {
                    "operationId": "listOpencastLectureEpisodes",
                    "tags": ["lectures"],
                    "parameters": [{"name": "module_id"}],
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": f"{SCHEMA_REF_PREFIX}LectureResponse"},
                                },
                            },
                        },
                    },
                },
            },
        },
        "components": {
            "schemas": {
                "LectureResponse": {
                    "properties": {
                        "course_id": {"type": "integer"},
                        "origin": {"enum": ["lecture", "exam"]},
                        "pinned": {"const": "opencast", "type": "string"},
                        "nested": {"properties": {"episode_id": {"type": "string"}}},
                    },
                },
            },
        },
    }

    offenders = _source_vocabulary_offenders(document)

    assert offenders == [
        "GET /api/learning-paths operationId listOpencastLectureEpisodes",
        "GET /api/learning-paths tag lectures",
        "GET /api/learning-paths parameter module_id",
        "schema LectureResponse",
        "schema LectureResponse property course_id",
        "schema LectureResponse property origin literal value lecture",
        "schema LectureResponse property pinned literal value opencast",
        "schema LectureResponse property nested property episode_id",
    ]


def _core_paths(document: dict[str, Any]) -> Iterator[str]:
    for path in document["paths"]:
        if not path.startswith(INTEGRATIONS_PREFIX):
            yield path


def _source_vocabulary_offenders(document: dict[str, Any]) -> list[str]:
    offenders = list(_operation_offenders(document))
    schemas = document.get("components", {}).get("schemas", {})
    for name in sorted(_reachable_schemas(document, integrations=False)):
        schema = schemas.get(name, {})
        if SOURCE_VOCABULARY.search(name):
            offenders.append(f"schema {name}")
        offenders.extend(f"schema {name} {label}" for label in _schema_offenders(schema))
    return offenders


def _operation_offenders(document: dict[str, Any]) -> Iterator[str]:
    for path, path_item in document["paths"].items():
        if path.startswith(INTEGRATIONS_PREFIX):
            continue
        for parameter in path_item.get("parameters", []):
            name = str(parameter.get("name", ""))
            if SOURCE_VOCABULARY.search(name):
                yield f"{path} parameter {name}"
        for method, operation in path_item.items():
            if method not in HTTP_METHODS:
                continue
            label = f"{method.upper()} {path}"
            operation_id = str(operation.get("operationId", ""))
            if SOURCE_VOCABULARY.search(operation_id):
                yield f"{label} operationId {operation_id}"
            for tag in operation.get("tags", []):
                if SOURCE_VOCABULARY.search(str(tag)):
                    yield f"{label} tag {tag}"
            for parameter in operation.get("parameters", []):
                name = str(parameter.get("name", ""))
                if SOURCE_VOCABULARY.search(name):
                    yield f"{label} parameter {name}"


def _schema_offenders(node: object, trail: str = "") -> Iterator[str]:
    """Walk a schema body, reporting property names and enum values at any depth."""
    if isinstance(node, dict):
        for property_name, property_schema in node.get("properties", {}).items():
            here = f"{trail}property {property_name}"
            if SOURCE_VOCABULARY.search(str(property_name)):
                yield here
            yield from _schema_offenders(property_schema, f"{here} ")
        # Pydantic emits `const` rather than `enum` for a single-valued Literal.
        for value in _literal_values(node):
            if SOURCE_VOCABULARY.search(str(value)):
                yield f"{trail}literal value {value}"
        for key, value in node.items():
            if key in {"properties", "enum", "const"}:
                continue
            yield from _schema_offenders(value, trail)
    elif isinstance(node, list):
        for item in node:
            yield from _schema_offenders(item, trail)


def _literal_values(node: dict[str, Any]) -> list[object]:
    values = list(node.get("enum", []))
    if "const" in node:
        values.append(node["const"])
    return values


def _reachable_schemas(document: dict[str, Any], *, integrations: bool) -> set[str]:
    """Return schema names reachable from integration or from core paths."""
    schemas = document.get("components", {}).get("schemas", {})
    pending = [
        ref
        for path, path_item in document["paths"].items()
        if path.startswith(INTEGRATIONS_PREFIX) is integrations
        for ref in _schema_refs(path_item)
    ]

    reachable: set[str] = set()
    while pending:
        name = pending.pop()
        if name in reachable:
            continue
        reachable.add(name)
        pending.extend(_schema_refs(schemas.get(name, {})))
    return reachable


def _schema_refs(node: object) -> Iterator[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str) and value.startswith(SCHEMA_REF_PREFIX):
                yield value.removeprefix(SCHEMA_REF_PREFIX)
            else:
                yield from _schema_refs(value)
    elif isinstance(node, list):
        for item in node:
            yield from _schema_refs(item)
