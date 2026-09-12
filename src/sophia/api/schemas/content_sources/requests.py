"""Content source API request DTOs."""

from __future__ import annotations

from fastapi import UploadFile  # noqa: TC002 — Pydantic resolves this annotation at runtime
from pydantic import BaseModel


class ContentSourceUploadForm(BaseModel):
    """The multipart body of a content-source upload.

    A model rather than loose ``Form``/``File`` parameters so the generated
    contract carries a named component: FastAPI names an inferred multipart
    body ``Body_<operation>``, which the schema-stability check rejects and a
    generated client would re-export under a name that moves whenever the
    handler is renamed.

    Not an :class:`~sophia.api.schemas.common.ApiModel`: ``UploadFile`` is a
    stream handle, and freezing the model would promise an immutability the
    handle does not have.
    """

    title: str
    file: UploadFile
