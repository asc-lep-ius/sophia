"""Stable OpenAPI operation contracts for issue #94 domain routers."""

from __future__ import annotations

from typing import cast

from ._session_helpers import build_harness

DOMAIN_OPERATION_CONTRACTS: dict[tuple[str, str], tuple[str, str]] = {
    ("get", "/api/content-sources"): (
        "listContentSources",
        "#/components/schemas/ContentSourceListResponse",
    ),
    ("post", "/api/content-sources/discover"): (
        "discoverContentSources",
        "#/components/schemas/ContentSourceDiscoveryResponse",
    ),
    ("get", "/api/content-sources/{content_source_id}/content-items"): (
        "listContentItems",
        "#/components/schemas/ContentItemListResponse",
    ),
    ("get", "/api/content-sources/{content_source_id}/ingestion-status"): (
        "readContentSourceIngestionStatus",
        "#/components/schemas/ContentSourceIngestionStatusResponse",
    ),
    ("get", "/api/topics"): ("listTopics", "#/components/schemas/TopicListResponse"),
    ("post", "/api/topics/extract"): (
        "extractTopics",
        "#/components/schemas/TopicExtractionResponse",
    ),
    ("post", "/api/topics/manual"): ("saveManualTopic", "#/components/schemas/TopicResponse"),
    ("get", "/api/topics/confidence"): (
        "listTopicConfidenceRatings",
        "#/components/schemas/TopicConfidenceListResponse",
    ),
    ("post", "/api/topics/confidence"): (
        "saveTopicConfidenceRating",
        "#/components/schemas/TopicConfidenceResponse",
    ),
    ("get", "/api/study/sessions"): (
        "listStudySessions",
        "#/components/schemas/StudySessionListResponse",
    ),
    ("post", "/api/study/sessions"): (
        "startStudySession",
        "#/components/schemas/StudySessionResponse",
    ),
    ("post", "/api/study/sessions/{session_id}/complete"): (
        "completeStudySession",
        "#/components/schemas/StudySessionCompletionResponse",
    ),
    ("post", "/api/study/flashcards"): (
        "saveStudyFlashcard",
        "#/components/schemas/StudyFlashcardResponse",
    ),
    ("get", "/api/review/due"): (
        "listDueReviews",
        "#/components/schemas/DueReviewListResponse",
    ),
    ("get", "/api/review/upcoming"): (
        "listUpcomingReviews",
        "#/components/schemas/UpcomingReviewListResponse",
    ),
    ("get", "/api/review/schedules"): (
        "listReviewSchedules",
        "#/components/schemas/ReviewScheduleListResponse",
    ),
    ("post", "/api/review/schedules"): (
        "scheduleReview",
        "#/components/schemas/ReviewScheduleResponse",
    ),
    ("post", "/api/review/complete"): (
        "completeReview",
        "#/components/schemas/ReviewScheduleResponse",
    ),
    ("get", "/api/chronos/deadlines"): (
        "listChronosDeadlines",
        "#/components/schemas/ChronosDeadlineListResponse",
    ),
    ("post", "/api/chronos/sync"): (
        "syncChronosDeadlines",
        "#/components/schemas/ChronosSyncResponse",
    ),
    ("post", "/api/chronos/estimates"): (
        "recordChronosEstimate",
        "#/components/schemas/ChronosEstimateResponse",
    ),
    ("post", "/api/chronos/timers/{deadline_id}/start"): (
        "startChronosTimer",
        "#/components/schemas/ChronosTimerStartResponse",
    ),
    ("post", "/api/chronos/timers/{deadline_id}/stop"): (
        "stopChronosTimer",
        "#/components/schemas/ChronosTimerStopResponse",
    ),
    ("get", "/api/chronos/deadlines/{deadline_id}/tracked-time"): (
        "getChronosTrackedTime",
        "#/components/schemas/ChronosTrackedTimeResponse",
    ),
    ("post", "/api/chronos/time-entries"): (
        "recordChronosTimeEntry",
        "#/components/schemas/ChronosTimeEntryResponse",
    ),
    ("post", "/api/chronos/reflections"): (
        "recordChronosReflection",
        "#/components/schemas/ChronosReflectionResponse",
    ),
    ("post", "/api/chronos/deadlines/{deadline_id}/complete"): (
        "completeChronosDeadline",
        "#/components/schemas/ChronosCompletionResponse",
    ),
    ("get", "/api/chronos/workload"): (
        "getChronosWorkload",
        "#/components/schemas/ChronosWorkloadResponse",
    ),
    ("get", "/api/chronos/upcoming-exams"): (
        "listChronosUpcomingExams",
        "#/components/schemas/ChronosUpcomingExamListResponse",
    ),
    ("get", "/api/chronos/ics"): (
        "exportChronosIcs",
        "#/components/schemas/ChronosIcsExportResponse",
    ),
    ("get", "/api/chronos-history/deadlines"): (
        "listChronosHistoryDeadlines",
        "#/components/schemas/ChronosHistoryDeadlineListResponse",
    ),
    ("get", "/api/chronos-history/deadlines/{deadline_id}/reflection"): (
        "getChronosHistoryReflection",
        "#/components/schemas/ChronosHistoryReflectionResponse",
    ),
    ("get", "/api/chronos-history/deadlines/{deadline_id}/time-entries"): (
        "listChronosHistoryTimeEntries",
        "#/components/schemas/ChronosHistoryTimeEntryListResponse",
    ),
    ("get", "/api/chronos-history/effort-distribution"): (
        "getChronosHistoryEffortDistribution",
        "#/components/schemas/ChronosHistoryEffortDistributionResponse",
    ),
    ("get", "/api/chronos-history/calibration"): (
        "getChronosHistoryCalibration",
        "#/components/schemas/ChronosHistoryCalibrationResponse",
    ),
    ("post", "/api/search"): (
        "searchContent",
        "#/components/schemas/ContentSearchResponse",
    ),
    ("get", "/api/calibration/ratings"): (
        "listCalibrationRatings",
        "#/components/schemas/CalibrationRatingListResponse",
    ),
    ("get", "/api/calibration/blind-spots"): (
        "listCalibrationBlindSpots",
        "#/components/schemas/CalibrationRatingListResponse",
    ),
    ("post", "/api/calibration/ratings"): (
        "saveCalibrationConfidenceRating",
        "#/components/schemas/CalibrationRatingSavedResponse",
    ),
    ("patch", "/api/calibration/actual-score"): (
        "updateCalibrationActualScore",
        "#/components/schemas/ActualScoreUpdateResponse",
    ),
    ("get", "/api/quickstart/overview"): (
        "getQuickstartOverview",
        "#/components/schemas/QuickstartOverviewResponse",
    ),
    ("post", "/api/quickstart/confidence"): (
        "saveQuickstartConfidence",
        "#/components/schemas/QuickstartConfidenceResponse",
    ),
    ("post", "/api/quickstart/manual-topics"): (
        "saveQuickstartManualTopics",
        "#/components/schemas/QuickstartManualTopicsResponse",
    ),
    ("get", "/api/quickstart/session-count"): (
        "getQuickstartSessionCount",
        "#/components/schemas/QuickstartSessionCountResponse",
    ),
}


def test_issue_94_domain_operation_ids_are_stable() -> None:
    openapi_paths = build_harness().app.openapi()["paths"]

    actual_operation_ids = {
        (method, path): openapi_paths[path][method]["operationId"]
        for method, path in DOMAIN_OPERATION_CONTRACTS
    }
    expected_operation_ids = {
        route: operation_id
        for route, (operation_id, _response_schema_ref) in DOMAIN_OPERATION_CONTRACTS.items()
    }

    assert actual_operation_ids == expected_operation_ids


def test_issue_94_domain_responses_use_explicit_json_component_schemas() -> None:
    openapi_paths = build_harness().app.openapi()["paths"]

    actual_response_schemas = {
        (method, path): _json_response_schema(openapi_paths[path][method]).get("$ref")
        for method, path in DOMAIN_OPERATION_CONTRACTS
    }
    expected_response_schemas = {
        route: response_schema_ref
        for route, (_operation_id, response_schema_ref) in DOMAIN_OPERATION_CONTRACTS.items()
    }

    assert actual_response_schemas == expected_response_schemas


def _json_response_schema(operation: dict[str, object]) -> dict[str, object]:
    responses = cast("dict[str, object]", operation["responses"])
    success_response = cast("dict[str, object]", responses["200"])
    content = cast("dict[str, object]", success_response["content"])
    json_media_type = cast("dict[str, object]", content["application/json"])
    schema = json_media_type["schema"]

    assert schema != {}
    assert isinstance(schema, dict)
    return schema
