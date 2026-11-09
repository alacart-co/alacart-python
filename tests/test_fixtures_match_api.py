"""Check the test fixtures, and the client's coverage, against the API's OpenAPI document.

The fixtures are written by hand, so this test keeps them honest. `tests/openapi.v1.json` is a
copy of the document that beta serves at `https://api.test.alacart.io/openapi/v1.json`.
"""

from __future__ import annotations

import pytest
from jsonschema import Draft202012Validator

from alacart import AlacartClient

from .conftest import FIXTURES, OPENAPI, load_fixture, openapi_registry, schema_ref

REGISTRY = openapi_registry(OPENAPI)

# Each fixture, with the endpoint and status whose documented schema it must match.
FIXTURE_RESPONSES: dict[str, tuple[str, str, str]] = {
    "me": ("get", "/v1/me", "200"),
    "stores": ("get", "/v1/stores", "200"),
    "item_lists": ("get", "/v1/item-lists", "200"),
    "item_list": ("post", "/v1/item-lists", "201"),
    "items": ("get", "/v1/items", "200"),
    "added_items": ("post", "/v1/items", "200"),
    "item": ("patch", "/v1/items/{itemId}", "200"),
    "sorted_items": ("get", "/v1/item-lists/{listId}/sorted", "200"),
    "favorites": ("get", "/v1/items/favorites", "200"),
    "suggestions": ("get", "/v1/items/suggestions", "200"),
    "recipe_search": ("get", "/v1/recipe-box", "200"),
    "recipe": ("get", "/v1/recipe-box/{recipeId}", "200"),
    "recipe_ingredients": ("get", "/v1/recipe-box/{recipeId}/ingredients", "200"),
    "recipe_summary": ("post", "/v1/recipe-box", "201"),
    "meal_plan": ("get", "/v1/meal-plans/active", "200"),
    "added_meals": ("post", "/v1/meal-plans/active/meals", "201"),
    "meal": ("patch", "/v1/meal-plans/active/meals/{mealId}", "200"),
    "problem_invalid_request": ("post", "/v1/items", "400"),
    "problem_invalid_token": ("get", "/v1/me", "401"),
    "problem_premium_required": ("get", "/v1/me", "403"),
    "problem_not_found": ("get", "/v1/items", "404"),
    "problem_conflict": ("post", "/v1/item-lists", "409"),
    "problem_limit_reached_items": ("post", "/v1/items", "409"),
    "problem_limit_reached_meals": ("post", "/v1/meal-plans/active/meals", "409"),
    "problem_recipe_import_failed": ("post", "/v1/recipe-box/import", "422"),
    "problem_rate_limited": ("get", "/v1/me", "429"),
    "problem_unavailable": ("post", "/v1/recipe-box/import", "503"),
}

# Each operation in the OpenAPI document, with the client method that calls it.
CLIENT_METHODS: dict[str, str] = {
    "getMe": "get_me",
    "getStores": "get_stores",
    "getItemLists": "get_item_lists",
    "createItemList": "create_item_list",
    "changeItemList": "change_item_list",
    "deleteItemList": "delete_item_list",
    "getSortedItems": "get_sorted_items",
    "setManualOrder": "set_manual_order",
    "getItems": "get_items",
    "addItems": "add_items",
    "changeItem": "change_item",
    "removeItem": "remove_item",
    "getFavoriteItems": "get_favorite_items",
    "getItemSuggestions": "get_item_suggestions",
    "searchRecipeBox": "search_recipe_box",
    "getRecipe": "get_recipe",
    "getRecipeIngredients": "get_recipe_ingredients",
    "addRecipe": "add_recipe",
    "importRecipe": "import_recipe",
    "deleteRecipe": "delete_recipe",
    "getActiveMealPlan": "get_active_meal_plan",
    "addMeals": "add_meals",
    "changeMeal": "change_meal",
    "removeMeal": "remove_meal",
}


def _response_schema(method: str, path: str, status: str) -> dict[str, str]:
    content = OPENAPI["paths"][path][method]["responses"][status]["content"]
    (media_type,) = content
    return schema_ref("paths", path, method, "responses", status, "content", media_type, "schema")


@pytest.mark.parametrize("name", sorted(FIXTURE_RESPONSES))
def test_fixture_matches_the_documented_schema(name: str) -> None:
    method, path, status = FIXTURE_RESPONSES[name]
    validator = Draft202012Validator(_response_schema(method, path, status), registry=REGISTRY)
    errors = [error.message for error in validator.iter_errors(load_fixture(name))]
    assert errors == []


def test_every_fixture_file_is_checked() -> None:
    files = {path.stem for path in FIXTURES.glob("*.json")}
    assert files == set(FIXTURE_RESPONSES)


def test_the_client_covers_every_operation() -> None:
    operations = {
        operation["operationId"]
        for path_item in OPENAPI["paths"].values()
        for operation in path_item.values()
        if isinstance(operation, dict) and "operationId" in operation
    }
    assert operations == set(CLIENT_METHODS)
    for method in CLIENT_METHODS.values():
        assert callable(getattr(AlacartClient, method))
