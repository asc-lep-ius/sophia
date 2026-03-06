"""Tests for the URL resource classifier."""

from __future__ import annotations

import pytest

from sophia.domain.models import ContentInfo, CourseResource, ModuleInfo, ResourceCategory
from sophia.services.resource_classifier import classify_modules, classify_url, is_book_resource


class TestClassifyUrl:
    """Test domain-based and keyword-based URL classification."""

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://link.springer.com/book/10.1007/978-3-658-21155-0", ResourceCategory.BOOK),
            ("https://www.dpunkt.de/buecher/1234.html", ResourceCategory.BOOK),
            ("https://www.pearson.com/store/p/some-book/P100000", ResourceCategory.BOOK),
            ("https://www.wiley.com/en-us/some-title", ResourceCategory.BOOK),
            ("https://www.oreilly.com/library/view/some-book/", ResourceCategory.BOOK),
            ("https://www.youtube.com/watch?v=abc123", ResourceCategory.TUTORIAL),
            ("https://youtu.be/abc123", ResourceCategory.TUTORIAL),
            ("https://www.khanacademy.org/math/linear-algebra", ResourceCategory.TUTORIAL),
            ("https://docs.python.org/3/library/asyncio.html", ResourceCategory.DOCUMENTATION),
            ("https://developer.mozilla.org/en-US/docs/Web", ResourceCategory.DOCUMENTATION),
            ("https://docs.oracle.com/en/java/javase/17/docs/", ResourceCategory.DOCUMENTATION),
            ("https://leetcode.com/problems/two-sum/", ResourceCategory.PRACTICE),
            ("https://www.hackerrank.com/challenges/some-task", ResourceCategory.PRACTICE),
            ("https://exercism.org/tracks/python", ResourceCategory.PRACTICE),
            ("https://www.jetbrains.com/idea/", ResourceCategory.TOOL),
            ("https://github.com/some/repo", ResourceCategory.TOOL),
            ("https://gitlab.com/some/project", ResourceCategory.TOOL),
            ("https://example.com/something", ResourceCategory.OTHER),
            ("https://tuwel.tuwien.ac.at/mod/resource/view.php", ResourceCategory.OTHER),
        ],
        ids=[
            "springer",
            "dpunkt",
            "pearson",
            "wiley",
            "oreilly",
            "youtube",
            "youtu.be",
            "khanacademy",
            "docs.python",
            "mdn",
            "docs.oracle",
            "leetcode",
            "hackerrank",
            "exercism",
            "jetbrains",
            "github",
            "gitlab",
            "unknown",
            "tuwel",
        ],
    )
    def test_domain_classification(self, url: str, expected: ResourceCategory) -> None:
        assert classify_url(url) == expected

    @pytest.mark.parametrize(
        ("name", "url", "expected"),
        [
            ("Literatur zum Kurs", "https://www.example.com/stuff", ResourceCategory.BOOK),
            ("Online-Bücher", "https://random.com/link", ResourceCategory.BOOK),
            ("Pflichtliteratur", "https://example.com/", ResourceCategory.BOOK),
            ("Empfohlene Lektüre", "https://youtube.com/watch?v=x", ResourceCategory.BOOK),
            ("Lehrbuch zum Kurs", "https://example.org/page", ResourceCategory.BOOK),
            ("Reading List", "https://example.com/list", ResourceCategory.BOOK),
            ("Tutorial: Getting Started", "https://example.com/", ResourceCategory.TUTORIAL),
            ("Video: Introduction", "https://example.com/intro", ResourceCategory.TUTORIAL),
            ("Screencast zur Vorlesung", "https://example.com/sc", ResourceCategory.TUTORIAL),
            ("Übung 1", "https://example.com/ex", ResourceCategory.PRACTICE),
            ("Exercise Sheet 3", "https://example.com/sheet", ResourceCategory.PRACTICE),
        ],
        ids=[
            "literatur",
            "buecher",
            "pflichtliteratur",
            "lektuere-overrides-youtube",
            "lehrbuch",
            "reading-list",
            "tutorial",
            "video",
            "screencast",
            "uebung",
            "exercise",
        ],
    )
    def test_name_overrides_domain(
        self, name: str, url: str, expected: ResourceCategory
    ) -> None:
        assert classify_url(url, activity_name=name) == expected

    def test_empty_url_returns_other(self) -> None:
        assert classify_url("") == ResourceCategory.OTHER

    def test_malformed_url_returns_other(self) -> None:
        assert classify_url("not-a-url") == ResourceCategory.OTHER

    def test_case_insensitive_name_matching(self) -> None:
        result = classify_url("https://example.com", activity_name="LITERATUR")
        assert result == ResourceCategory.BOOK

    def test_subdomain_matching(self) -> None:
        """Subdomains of known domains should still match."""
        assert classify_url("https://www.springer.com/book/123") == ResourceCategory.BOOK
        assert classify_url("https://m.youtube.com/watch?v=x") == ResourceCategory.TUTORIAL


class TestClassifyModules:
    """Test classification of ModuleInfo lists into CourseResource objects."""

    def test_only_url_modules_processed(self) -> None:
        """Non-URL modules are ignored."""
        modules = [
            ModuleInfo(id=1, name="Some Book", modname="book", url="https://example.com"),
            ModuleInfo(id=2, name="A Page", modname="page", url="https://example.com"),
            ModuleInfo(
                id=3,
                name="Springer Link",
                modname="url",
                url="https://link.springer.com/book/123",
            ),
        ]
        result = classify_modules(modules, course_id=42, course_name="Test Course")

        assert len(result) == 1
        assert result[0].title == "Springer Link"
        assert result[0].category == ResourceCategory.BOOK
        assert result[0].course_id == 42
        assert result[0].course_name == "Test Course"

    def test_url_from_contents(self) -> None:
        """URL is extracted from contents when module.url is not set."""
        modules = [
            ModuleInfo(
                id=1,
                name="LeetCode Practice",
                modname="url",
                contents=[
                    ContentInfo(
                        filename="",
                        fileurl="https://leetcode.com/problems/",
                        filesize=0,
                    )
                ],
            ),
        ]
        result = classify_modules(modules, course_id=1)

        assert len(result) == 1
        assert result[0].category == ResourceCategory.PRACTICE

    def test_empty_modules(self) -> None:
        assert classify_modules([], course_id=1) == []

    def test_url_module_without_url_skipped(self) -> None:
        """URL modules with no extractable URL are skipped."""
        modules = [
            ModuleInfo(id=1, name="Broken Link", modname="url"),
        ]
        result = classify_modules(modules, course_id=1)
        assert result == []

    def test_description_preserved(self) -> None:
        """Module description is carried into the CourseResource."""
        modules = [
            ModuleInfo(
                id=1,
                name="GitHub Repo",
                modname="url",
                url="https://github.com/example/repo",
                description="The main project repository",
            ),
        ]
        result = classify_modules(modules, course_id=1)

        assert len(result) == 1
        assert result[0].description == "The main project repository"
        assert result[0].category == ResourceCategory.TOOL


class TestIsBookResource:
    """Test the is_book_resource helper."""

    def test_book_category_returns_true(self) -> None:
        resource = CourseResource(
            url="https://springer.com/book",
            title="Some Book",
            category=ResourceCategory.BOOK,
            course_id=1,
        )
        assert is_book_resource(resource) is True

    @pytest.mark.parametrize(
        "category",
        [
            ResourceCategory.TUTORIAL,
            ResourceCategory.DOCUMENTATION,
            ResourceCategory.PRACTICE,
            ResourceCategory.TOOL,
            ResourceCategory.OTHER,
        ],
    )
    def test_non_book_categories_return_false(self, category: ResourceCategory) -> None:
        resource = CourseResource(
            url="https://example.com",
            title="Something",
            category=category,
            course_id=1,
        )
        assert is_book_resource(resource) is False
