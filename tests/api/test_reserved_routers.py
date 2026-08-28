"""Reserved routers are visible in the contract and unavailable at runtime."""

from __future__ import annotations

from fastapi.testclient import TestClient

from sophia.api import create_api_app

RESERVED_ROUTES = (
    ("post", "/api/tutoring/turns"),
    ("get", "/api/worked-examples"),
    ("get", "/api/problems"),
    ("get", "/api/instructor/provenance-review"),
)


def test_reserved_routes_are_present_in_the_openapi_document() -> None:
    document = create_api_app().openapi()

    missing = [
        f"{method.upper()} {path}"
        for method, path in RESERVED_ROUTES
        if method not in document["paths"].get(path, {})
    ]

    assert missing == []


def test_reserved_routes_declare_a_501_response() -> None:
    document = create_api_app().openapi()

    undeclared = [
        f"{method.upper()} {path}"
        for method, path in RESERVED_ROUTES
        if "501" not in document["paths"][path][method]["responses"]
    ]

    assert undeclared == []


def test_reserved_routes_return_501_with_feature_not_implemented() -> None:
    client = TestClient(create_api_app(), base_url="https://testserver")

    outcomes = {
        f"{method.upper()} {path}": client.request(method, path).json()
        for method, path in RESERVED_ROUTES
    }
    statuses = {
        f"{method.upper()} {path}": client.request(method, path).status_code
        for method, path in RESERVED_ROUTES
    }

    assert set(statuses.values()) == {501}
    for body in outcomes.values():
        assert body["detail"]["code"] == "feature.not_implemented"


def test_reserved_routes_do_not_require_authentication_to_report_unavailability() -> None:
    """A 501 must not masquerade as a 401; the feature is absent, not protected."""
    client = TestClient(create_api_app(), base_url="https://testserver")

    response = client.get("/api/problems")

    assert response.status_code == 501
