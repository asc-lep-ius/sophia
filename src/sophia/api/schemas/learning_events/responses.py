"""Learning event ingestion response DTOs."""

from __future__ import annotations

from sophia.api.schemas.common import ApiModel


class LearningEventBatchResponse(ApiModel):
    """Outcome of ingesting a batch.

    ``duplicate`` counts events already recorded under the same ``event_id``;
    a retried batch therefore reports zero accepted rather than failing.
    """

    learning_path_id: int
    accepted: int
    duplicate: int
