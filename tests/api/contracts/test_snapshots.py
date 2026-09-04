"""Snapshot fixtures for stable API transport contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sophia.api.schemas.auth import AuthSessionResponse
from sophia.api.schemas.errors import ErrorEnvelope
from sophia.api.schemas.health import HealthResponse, ReadinessResponse
from sophia.api.schemas.metrics import WebVitalsAcceptedResponse
from sophia.api.schemas.settings import SettingsResponse

if TYPE_CHECKING:
    from sophia.api.schemas.common import ApiModel


CONTRACT_DIR = Path(__file__).parent
SNAPSHOT_CASES: tuple[tuple[str, type[ApiModel]], ...] = (
    ("auth_session_response.json", AuthSessionResponse),
    ("anonymous_session_response.json", AuthSessionResponse),
    ("health_response.json", HealthResponse),
    ("readiness_response.json", ReadinessResponse),
    ("error_envelope.json", ErrorEnvelope),
    ("settings_response.json", SettingsResponse),
    ("web_vitals_accepted_response.json", WebVitalsAcceptedResponse),
)


@pytest.mark.parametrize(("fixture_name", "model_type"), SNAPSHOT_CASES)
def test_contract_snapshot_validates_against_pydantic_model(
    fixture_name: str,
    model_type: type[ApiModel],
) -> None:
    snapshot = json.loads((CONTRACT_DIR / fixture_name).read_text())

    model = model_type.model_validate(snapshot)

    assert model.model_dump(mode="json") == snapshot
