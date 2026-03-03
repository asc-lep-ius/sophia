"""Domain error hierarchy."""


class SophiaError(Exception):
    """Base error for all Sophia exceptions."""


class AuthError(SophiaError):
    """Authentication failed — token expired or invalid."""


class MoodleError(SophiaError):
    """Moodle API returned an error response."""


class SearchError(SophiaError):
    """Book search failed."""


class DownloadError(SophiaError):
    """File download failed."""


class ExtractionError(SophiaError):
    """Reference extraction failed."""


class RenderError(SophiaError):
    """Report rendering failed."""
