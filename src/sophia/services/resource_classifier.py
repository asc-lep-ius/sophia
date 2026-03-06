"""Classify course URL resources into categories using domain and name heuristics."""

from __future__ import annotations

from urllib.parse import urlparse

from sophia.domain.models import CourseResource, ModuleInfo, ResourceCategory

# Domain → category mapping
_BOOK_DOMAINS: frozenset[str] = frozenset(
    {
        "springer.com",
        "link.springer.com",
        "dpunkt.de",
        "rheinwerk-verlag.de",
        "pearson.com",
        "wiley.com",
        "oreilly.com",
        "heldermann.de",
        "addison-wesley.de",
        "cambridge.org",
        "oxford.press",
        "degruyter.com",
        "hanser-fachbuch.de",
    }
)

_TUTORIAL_DOMAINS: frozenset[str] = frozenset(
    {
        "youtube.com",
        "youtu.be",
        "tutorialspoint.com",
        "khanacademy.org",
        "coursera.org",
        "udemy.com",
        "edx.org",
    }
)

_DOCUMENTATION_DOMAINS: frozenset[str] = frozenset(
    {
        "docs.oracle.com",
        "developer.mozilla.org",
        "docs.python.org",
        "cppreference.com",
        "devdocs.io",
    }
)

_PRACTICE_DOMAINS: frozenset[str] = frozenset(
    {
        "codechef.com",
        "codingbat.com",
        "edabit.com",
        "leetcode.com",
        "hackerrank.com",
        "exercism.org",
        "codeforces.com",
    }
)

_TOOL_DOMAINS: frozenset[str] = frozenset(
    {
        "jetbrains.com",
        "github.com",
        "gitlab.com",
        "visualstudio.com",
    }
)

# Activity name keywords that override domain heuristics
_BOOK_KEYWORDS: frozenset[str] = frozenset(
    {
        "literatur",
        "buch",
        "book",
        "textbook",
        "bücher",
        "pflichtliteratur",
        "empfohlene lektüre",
        "reading list",
        "lehrbuch",
    }
)

_TUTORIAL_KEYWORDS: frozenset[str] = frozenset(
    {
        "tutorial",
        "video",
        "screencast",
        "vorlesung",
    }
)

_PRACTICE_KEYWORDS: frozenset[str] = frozenset(
    {
        "übung",
        "exercise",
        "practice",
        "aufgabe",
    }
)

# Maps each domain set to its category for iteration
_DOMAIN_CATEGORIES: list[tuple[frozenset[str], ResourceCategory]] = [
    (_BOOK_DOMAINS, ResourceCategory.BOOK),
    (_TUTORIAL_DOMAINS, ResourceCategory.TUTORIAL),
    (_DOCUMENTATION_DOMAINS, ResourceCategory.DOCUMENTATION),
    (_PRACTICE_DOMAINS, ResourceCategory.PRACTICE),
    (_TOOL_DOMAINS, ResourceCategory.TOOL),
]

# Maps each keyword set to its category (checked before domain heuristics)
_KEYWORD_CATEGORIES: list[tuple[frozenset[str], ResourceCategory]] = [
    (_BOOK_KEYWORDS, ResourceCategory.BOOK),
    (_TUTORIAL_KEYWORDS, ResourceCategory.TUTORIAL),
    (_PRACTICE_KEYWORDS, ResourceCategory.PRACTICE),
]


def _match_domain(hostname: str, domains: frozenset[str]) -> bool:
    """Check if a hostname matches any domain in the set (suffix match)."""
    return any(hostname == d or hostname.endswith(f".{d}") for d in domains)


def classify_url(url: str, activity_name: str = "") -> ResourceCategory:
    """Classify a URL into a ResourceCategory based on domain and activity name.

    Activity name keywords take precedence over domain heuristics (a URL to youtube
    in a section called "Literatur" is likely a book-related video, not a tutorial).
    """
    name_lower = activity_name.lower()

    # Name-based heuristics override domain classification
    for keywords, category in _KEYWORD_CATEGORIES:
        if any(kw in name_lower for kw in keywords):
            return category

    # Fall back to domain-based classification
    try:
        hostname = urlparse(url).hostname or ""
    except ValueError:
        return ResourceCategory.OTHER

    hostname = hostname.lower()
    for domains, category in _DOMAIN_CATEGORIES:
        if _match_domain(hostname, domains):
            return category

    return ResourceCategory.OTHER


def classify_modules(
    modules: list[ModuleInfo],
    course_id: int,
    course_name: str = "",
) -> list[CourseResource]:
    """Classify URL modules from a course into CourseResource objects.

    Only processes modules with modname='url' that have a URL in their contents.
    """
    resources: list[CourseResource] = []

    for module in modules:
        if module.modname != "url":
            continue

        # URL modules store the target URL either in module.url or in contents
        target_url = _extract_url(module)
        if not target_url:
            continue

        category = classify_url(target_url, activity_name=module.name)
        resources.append(
            CourseResource(
                url=target_url,
                title=module.name,
                category=category,
                course_id=course_id,
                course_name=course_name,
                description=module.description,
            )
        )

    return resources


def _extract_url(module: ModuleInfo) -> str:
    """Extract the target URL from a URL module."""
    # Contents may have a fileurl pointing to the actual resource
    for content in module.contents:
        if content.fileurl:
            return content.fileurl

    # Fall back to the module's own URL
    return module.url or ""


def is_book_resource(resource: CourseResource) -> bool:
    """Check if a resource is classified as a book (for pipeline routing)."""
    return resource.category == ResourceCategory.BOOK
