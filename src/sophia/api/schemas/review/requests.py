"""Review API request DTOs."""

from __future__ import annotations

from typing import Self

from pydantic import Field, model_validator

from sophia.api.schemas.common import ApiModel


class ReviewScheduleRequest(ApiModel):
    learning_path_id: int = Field(gt=0)
    topic: str = Field(min_length=1)


class ReviewCompletionRequest(ApiModel):
    """One finished review, expressed either as a rating or as a raw score.

    ``self_rating`` is the Again/Hard/Good/Easy button the learner pressed; the
    server turns it into a score so no surface has to carry a copy of the
    scale. ``score`` stays for the callers that already compute one. Exactly
    one of them is required: accepting both would let a client claim a rating
    and a contradicting score in the same request, and the row would record
    whichever the server happened to prefer.
    """

    learning_path_id: int = Field(gt=0)
    topic: str = Field(min_length=1)
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    self_rating: int | None = Field(default=None, ge=1, le=4)

    @model_validator(mode="after")
    def check_exactly_one_grade(self) -> Self:
        if (self.score is None) == (self.self_rating is None):
            msg = "Provide exactly one of score or self_rating."
            raise ValueError(msg)
        return self
