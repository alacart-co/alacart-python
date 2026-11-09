"""Tests of the request check in `FakeApi`, so that the other tests can rely on it."""

from __future__ import annotations

from typing import Any

import pytest
from multidict import MultiDict

from .conftest import request_violations


def violations(
    method: str, path: str, query: dict[str, str] | None = None, body: Any = None
) -> list[str]:
    return request_violations(method, path, MultiDict(query or {}), body)


def test_a_documented_request_passes() -> None:
    assert violations("POST", "/v1/items", body={"texts": ["mjölk"], "listId": "1"}) == []
    assert violations("GET", "/v1/item-lists/1/sorted", {"storeId": "2"}) == []


@pytest.mark.parametrize(
    ("method", "path", "query", "body", "expected"),
    [
        ("POST", "/v1/items", None, {"texts": ["a"], "list_id": "1"}, "'list_id' was unexpected"),
        ("POST", "/v1/items", None, {"listId": "1"}, "'texts' is a required property"),
        ("POST", "/v1/items", None, {"texts": "a"}, "is not of type 'array'"),
        (
            "POST",
            "/v1/meal-plans/active/meals",
            None,
            {"meals": [{"type": "recipe", "recipeId": "1", "ingredients": [], "extra": 1}]},
            "'extra' was unexpected",
        ),
        ("GET", "/v1/items", {"list": "1"}, None, "undocumented query parameter list"),
        ("GET", "/v1/item-lists/1/sorted", None, None, "required query parameter storeId"),
        ("GET", "/v1/unknown", None, None, "matches 0 documented operations"),
        ("DELETE", "/v1/items/1", None, {"x": 1}, "a body that the document does not take"),
    ],
)
def test_a_request_that_breaks_the_document_is_reported(
    method: str, path: str, query: dict[str, str] | None, body: Any, expected: str
) -> None:
    found = violations(method, path, query, body)

    assert any(expected in violation for violation in found), found
