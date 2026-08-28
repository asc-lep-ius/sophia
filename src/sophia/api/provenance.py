"""Domain-to-transport mapping for provenance.

Kept out of ``schemas`` so the transport package stays free of domain imports,
and shared by every router that serves generated content.

The persisted origin names the concrete upstream system, because an audit trail
that forgets which system produced a claim is not much of an audit trail. The
published contract exposes only the *kind* of system, so the generated client
never learns which product a given deployment ingests from.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sophia.api.schemas.provenance import ContentOrigin, Provenance, ProvenanceAgent, SourceSpan
from sophia.domain.learning import ProvenanceAgent as DomainProvenanceAgent
from sophia.domain.learning import StoredContentOrigin

if TYPE_CHECKING:
    from sophia.domain.learning import ContentProvenance

API_CONTENT_ORIGIN = {StoredContentOrigin.TUWEL: ContentOrigin.LMS}
API_PROVENANCE_AGENT = {
    DomainProvenanceAgent.LEARNER: ProvenanceAgent.LEARNER,
    DomainProvenanceAgent.MODEL: ProvenanceAgent.MODEL,
}


def api_provenance(provenance: ContentProvenance) -> Provenance:
    """Project a stored provenance record onto the published contract."""
    return Provenance(
        origin=API_CONTENT_ORIGIN[provenance.origin],
        generated_by=API_PROVENANCE_AGENT[provenance.generated_by],
        generator_ref=provenance.generator_ref,
        generated_at=provenance.generated_at,
        verified_by=provenance.verified_by,
        verified_at=provenance.verified_at,
        source_spans=[
            SourceSpan(
                content_item_id=span.content_item_id,
                start_char=span.start_char,
                end_char=span.end_char,
                start_ms=span.start_ms,
                end_ms=span.end_ms,
                excerpt=span.excerpt,
            )
            for span in provenance.source_spans
        ],
    )
