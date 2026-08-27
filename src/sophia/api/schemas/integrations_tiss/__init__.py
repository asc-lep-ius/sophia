"""TISS integration API transport schemas."""

from sophia.api.schemas.integrations_tiss.requests import TissRegistrationAttemptRequest
from sophia.api.schemas.integrations_tiss.responses import (
    TissConnectionState,
    TissExamDateListResponse,
    TissExamDateResponse,
    TissFavoriteListResponse,
    TissFavoriteResponse,
    TissRegistrationAttemptResponse,
    TissRegistrationAttemptResultResponse,
    TissRegistrationGroupListResponse,
    TissRegistrationGroupResponse,
    TissRegistrationStatusResponse,
    TissRegistrationTargetResponse,
)

__all__ = [
    "TissConnectionState",
    "TissExamDateListResponse",
    "TissExamDateResponse",
    "TissFavoriteListResponse",
    "TissFavoriteResponse",
    "TissRegistrationAttemptRequest",
    "TissRegistrationAttemptResponse",
    "TissRegistrationAttemptResultResponse",
    "TissRegistrationGroupListResponse",
    "TissRegistrationGroupResponse",
    "TissRegistrationStatusResponse",
    "TissRegistrationTargetResponse",
]
