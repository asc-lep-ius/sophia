"""Athena service mirror coverage tests."""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING

from sophia.api.routers import calibration as calibration_router
from sophia.api.routers import study as study_router
from sophia.services import athena_confidence, athena_session

from ._session_helpers import build_harness

if TYPE_CHECKING:
    from collections.abc import Mapping
    from types import ModuleType


def test_athena_session_public_methods_are_mirrored_or_documented() -> None:
    operation_ids = _operation_ids()

    _assert_service_coverage(
        service_module=athena_session,
        coverage=study_router.ATHENA_SESSION_METHOD_COVERAGE,
        operation_ids=operation_ids,
    )


def test_athena_confidence_public_methods_are_mirrored_or_documented() -> None:
    operation_ids = _operation_ids()

    _assert_service_coverage(
        service_module=athena_confidence,
        coverage=calibration_router.ATHENA_CONFIDENCE_METHOD_COVERAGE,
        operation_ids=operation_ids,
    )


def _assert_service_coverage(
    *,
    service_module: ModuleType,
    coverage: Mapping[str, Mapping[str, str]],
    operation_ids: set[str],
) -> None:
    public_methods = _public_service_functions(service_module)

    assert set(coverage) == public_methods
    for method_name, entry in coverage.items():
        operation_id = entry.get("operation_id")
        rationale = entry.get("rationale")
        assert bool(operation_id) != bool(rationale), method_name
        if operation_id is not None:
            assert operation_id in operation_ids, method_name
        if rationale is not None:
            assert rationale.strip(), method_name


def _public_service_functions(service_module: ModuleType) -> set[str]:
    return {
        name
        for name, value in inspect.getmembers(service_module, inspect.isfunction)
        if not name.startswith("_") and value.__module__ == service_module.__name__
    }


def _operation_ids() -> set[str]:
    openapi = build_harness().app.openapi()
    operation_ids: set[str] = set()
    for path_item in openapi["paths"].values():
        for operation in path_item.values():
            operation_id = operation.get("operationId")
            if isinstance(operation_id, str):
                operation_ids.add(operation_id)
    return operation_ids
