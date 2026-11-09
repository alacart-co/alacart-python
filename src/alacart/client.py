"""The client for version 1 of the Alacart API."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, overload
from urllib.parse import quote

from aiohttp import ClientError

from ._parse import as_mapping, get_objects, get_str
from ._validate import check_id, check_ids, check_optional_id, check_strings
from .auth import AbstractAuth
from .exceptions import (
    AlacartApiError,
    AlacartConnectionError,
    AlacartResponseError,
    ConflictError,
    InsufficientScopeError,
    InvalidRequestError,
    InvalidTokenError,
    LimitReachedError,
    NotFoundError,
    PremiumRequiredError,
    RateLimitedError,
    RecipeImportFailedError,
    RetryLaterError,
    ServerError,
    UnavailableError,
)
from .models import (
    AddedItem,
    ImportedRecipe,
    Ingredient,
    Item,
    ItemList,
    ItemLists,
    ItemOrder,
    Items,
    Me,
    Meal,
    NewMeal,
    Recipe,
    RecipeSearchResult,
    RecipeSort,
    RecipeSummary,
    SortedItems,
    Store,
)

_ERRORS_BY_CODE: dict[str, type[AlacartApiError]] = {
    "invalid_request": InvalidRequestError,
    "invalid_token": InvalidTokenError,
    "insufficient_scope": InsufficientScopeError,
    "premium_required": PremiumRequiredError,
    "not_found": NotFoundError,
    "conflict": ConflictError,
    "limit_reached": LimitReachedError,
    "recipe_import_failed": RecipeImportFailedError,
    "rate_limited": RateLimitedError,
    "server_error": ServerError,
    "unavailable": UnavailableError,
}

# A gateway or proxy in front of the API can answer without a problem body. The status then
# picks the class.
_ERRORS_BY_STATUS: dict[int, type[AlacartApiError]] = {
    401: InvalidTokenError,
    404: NotFoundError,
    429: RateLimitedError,
    503: UnavailableError,
}


@dataclass(frozen=True, slots=True)
class _Answer:
    status: int
    headers: Mapping[str, str]
    data: Any


class AlacartClient:
    """Calls version 1 of the Alacart API on behalf of one signed-in user.

    Every method raises an `AlacartApiError` subclass when the API answers with an error, and
    `AlacartConnectionError` when it cannot reach the API. An exception from the auth's
    `async_get_access_token` reaches the caller unchanged. Every call needs a premium account,
    and a call that changes anything needs the `write` scope.

    An id argument must be an id that the API returned, as a string. A list argument must be a
    list or another sequence, never a single string.
    """

    def __init__(self, auth: AbstractAuth, *, request_timeout: float = 30) -> None:
        """Set up the client.

        `request_timeout` is how many seconds one call may take, from sending the request to
        reading the whole answer. The time the auth takes to return an access token does not
        count.
        """
        if not request_timeout > 0:
            raise ValueError("request_timeout must be more than 0 seconds")
        self._auth = auth
        self._request_timeout = request_timeout

    async def get_me(self) -> Me:
        """Return the account that the token acts for."""
        answer = await self._request("GET", "/v1/me")
        return Me.from_dict(as_mapping(answer.data))

    async def get_stores(self) -> list[Store]:
        """Return the stores the user has shopped in or marked as favorites."""
        answer = await self._request("GET", "/v1/stores")
        return get_objects(as_mapping(answer.data), "stores", Store.from_dict)

    # Item lists

    @overload
    async def get_item_lists(self, *, etag: None = None) -> ItemLists: ...

    @overload
    async def get_item_lists(self, *, etag: str) -> ItemLists | None: ...

    async def get_item_lists(self, *, etag: str | None = None) -> ItemLists | None:
        """Return the user's shopping lists, including lists that others share with the user.

        Pass the `etag` of an earlier answer to get None when nothing has changed since.
        """
        answer = await self._request("GET", "/v1/item-lists", etag=etag)
        if answer.status == 304:
            return None
        return ItemLists(
            item_lists=get_objects(as_mapping(answer.data), "itemLists", ItemList.from_dict),
            etag=answer.headers.get("ETag"),
        )

    async def create_item_list(self, name: str, *, is_private: bool | None = None) -> ItemList:
        """Create a shopping list and return it.

        A name that another list has raises `ConflictError`. `is_private` set to True hides the
        list from the others who share the account.
        """
        body: dict[str, Any] = {"name": name}
        _put_if_set(body, "isPrivate", is_private)
        answer = await self._request("POST", "/v1/item-lists", json_body=body)
        return ItemList.from_dict(as_mapping(answer.data))

    async def change_item_list(
        self, list_id: str, *, name: str | None = None, is_private: bool | None = None
    ) -> ItemList:
        """Rename a shopping list or change whether it is private, and return the list.

        The call must change at least one of the two. A name that another list has raises
        `ConflictError`, and so do two changes of `is_private`. One shows the account a list
        that another person shares with the user. The other makes the account's last shared
        list private.
        """
        body: dict[str, Any] = {}
        _put_if_set(body, "name", name)
        _put_if_set(body, "isPrivate", is_private)
        answer = await self._request(
            "PATCH", f"/v1/item-lists/{_id('list_id', list_id)}", json_body=body
        )
        return ItemList.from_dict(as_mapping(answer.data))

    async def delete_item_list(self, list_id: str) -> None:
        """Delete one of the user's shopping lists, with its items. It cannot be undone.

        A list that another person shares with the user leaves the user's lists, and its owner
        keeps it. The account's last shared list raises `ConflictError`.
        """
        await self._request("DELETE", f"/v1/item-lists/{_id('list_id', list_id)}")

    async def get_sorted_items(self, list_id: str, store_id: str) -> SortedItems:
        """Return a list's items grouped by the store's departments, in walking order."""
        answer = await self._request(
            "GET",
            f"/v1/item-lists/{_id('list_id', list_id)}/sorted",
            params=[("storeId", check_id("store_id", store_id))],
        )
        return SortedItems.from_dict(as_mapping(answer.data))

    async def set_manual_order(self, list_id: str, item_ids: Sequence[str]) -> None:
        """Set the order of a list's items by hand.

        Each id must belong to the list and appear once. Items left out, and items added later,
        come first. `get_items` with `ItemOrder.MANUAL` then returns the items in this order.
        """
        await self._request(
            "PUT",
            f"/v1/item-lists/{_id('list_id', list_id)}/manual-order",
            json_body={"itemIds": check_ids("item_ids", item_ids)},
        )

    # Items

    @overload
    async def get_items(
        self,
        *,
        list_id: str | None = None,
        order: ItemOrder | str | None = None,
        etag: None = None,
    ) -> Items: ...

    @overload
    async def get_items(
        self,
        *,
        list_id: str | None = None,
        order: ItemOrder | str | None = None,
        etag: str,
    ) -> Items | None: ...

    async def get_items(
        self,
        *,
        list_id: str | None = None,
        order: ItemOrder | str | None = None,
        etag: str | None = None,
    ) -> Items | None:
        """Return the items on the user's lists, newest first unless `order` says otherwise.

        Without `list_id`, the answer holds the items of every list. `ItemOrder.MANUAL` needs a
        `list_id`. Pass the `etag` of an earlier answer with the same arguments to get None when
        nothing has changed since.
        """
        params: list[tuple[str, str]] = []
        _param_if_set(params, "listId", check_optional_id("list_id", list_id))
        _param_if_set(params, "order", order)
        answer = await self._request("GET", "/v1/items", params=params, etag=etag)
        if answer.status == 304:
            return None
        return Items(
            items=get_objects(as_mapping(answer.data), "items", Item.from_dict),
            etag=answer.headers.get("ETag"),
        )

    async def add_items(
        self, texts: Sequence[str], *, list_id: str | None = None
    ) -> list[AddedItem]:
        """Add from 1 to 50 items to a shopping list, and return one entry per text.

        Leave out `list_id` for the default list. A text that names the same thing as an item
        on the list merges into that item. The call checks every text before it adds any. When
        the list fills up partway, it raises `LimitReachedError` with the items added before.
        """
        body: dict[str, Any] = {"texts": check_strings("texts", texts)}
        _put_if_set(body, "listId", check_optional_id("list_id", list_id))
        answer = await self._request("POST", "/v1/items", json_body=body)
        return get_objects(as_mapping(answer.data), "items", AddedItem.from_dict)

    async def change_item(
        self,
        item_id: str,
        *,
        text: str | None = None,
        list_id: str | None = None,
        is_permanent: bool | None = None,
        is_checked: bool | None = None,
    ) -> Item:
        """Change an item and return it. The call must change at least one field.

        `list_id` moves the item to that list. Checking a permanent item records the purchase,
        and the item stays on the list unchecked.
        """
        body: dict[str, Any] = {}
        _put_if_set(body, "text", text)
        _put_if_set(body, "listId", check_optional_id("list_id", list_id))
        _put_if_set(body, "isPermanent", is_permanent)
        _put_if_set(body, "isChecked", is_checked)
        answer = await self._request(
            "PATCH", f"/v1/items/{_id('item_id', item_id)}", json_body=body
        )
        return Item.from_dict(as_mapping(answer.data))

    async def remove_item(self, item_id: str) -> None:
        """Remove an item from its list."""
        await self._request("DELETE", f"/v1/items/{_id('item_id', item_id)}")

    async def get_favorite_items(self) -> list[str]:
        """Return the texts of the items the user buys often."""
        answer = await self._request("GET", "/v1/items/favorites")
        return _texts(as_mapping(answer.data), "favorites")

    async def get_item_suggestions(self, query: str) -> list[str]:
        """Return item texts that complete what the user has typed, best first.

        Each call counts against the rate limit, so wait until the user pauses typing. A
        suggestion service that is down or slow raises `UnavailableError`.
        """
        answer = await self._request("GET", "/v1/items/suggestions", params=[("query", query)])
        return _texts(as_mapping(answer.data), "suggestions")

    # Recipe box

    async def search_recipe_box(
        self,
        *,
        query: str | None = None,
        tags: Iterable[str] = (),
        sort: RecipeSort | str | None = None,
        max_cooking_time: int | None = None,
        min_grade: int | None = None,
        cooked: bool | None = None,
        own_recipes_only: bool | None = None,
        limit: int | None = None,
        offset: int | None = None,
        include_cook_count: bool = False,
        include_last_cooked_at: bool = False,
    ) -> RecipeSearchResult:
        """Search the user's recipe box, one page at a time.

        Without a query, tags or filters, it returns the whole recipe box. A recipe must have
        every tag in `tags`. `limit` is from 1 to 100, 50 by default. `RecipeSort.RANDOM` gives
        a new order on each call, so `offset` does not page through it.
        """
        params: list[tuple[str, str]] = []
        _param_if_set(params, "query", query)
        params.extend(("tags", tag) for tag in check_strings("tags", tags))
        _param_if_set(params, "sort", sort)
        _param_if_set(params, "maxCookingTime", max_cooking_time)
        _param_if_set(params, "minGrade", min_grade)
        _param_if_set(params, "cooked", cooked)
        _param_if_set(params, "ownRecipesOnly", own_recipes_only)
        _param_if_set(params, "limit", limit)
        _param_if_set(params, "offset", offset)
        _include(params, cookCount=include_cook_count, lastCookedAt=include_last_cooked_at)
        answer = await self._request("GET", "/v1/recipe-box", params=params)
        return RecipeSearchResult.from_dict(as_mapping(answer.data))

    async def get_recipe(
        self,
        recipe_id: str,
        *,
        include_cook_count: bool = False,
        include_last_cooked_at: bool = False,
    ) -> Recipe:
        """Return one recipe from the recipe box, with the user's own changes."""
        params: list[tuple[str, str]] = []
        _include(params, cookCount=include_cook_count, lastCookedAt=include_last_cooked_at)
        answer = await self._request(
            "GET", f"/v1/recipe-box/{_id('recipe_id', recipe_id)}", params=params
        )
        return Recipe.from_dict(as_mapping(answer.data))

    async def get_recipe_ingredients(
        self, recipe_id: str, *, portions: int | None = None, list_id: str | None = None
    ) -> list[Ingredient]:
        """Return a recipe's ingredients, each item once, compared with a shopping list.

        Leave out `portions` for the recipe's own portions, and `list_id` for the default list.
        """
        params: list[tuple[str, str]] = []
        _param_if_set(params, "portions", portions)
        _param_if_set(params, "listId", check_optional_id("list_id", list_id))
        answer = await self._request(
            "GET", f"/v1/recipe-box/{_id('recipe_id', recipe_id)}/ingredients", params=params
        )
        return get_objects(as_mapping(answer.data), "ingredients", Ingredient.from_dict)

    async def add_recipe(
        self,
        title: str,
        ingredients: Sequence[str],
        *,
        instructions: str | None = None,
        portions: int | None = None,
        description: str | None = None,
        tags: Sequence[str] | None = None,
    ) -> RecipeSummary:
        """Add a recipe that the app supplies as text, and return it."""
        body: dict[str, Any] = {
            "title": title,
            "ingredients": check_strings("ingredients", ingredients),
        }
        _put_if_set(body, "instructions", instructions)
        _put_if_set(body, "portions", portions)
        _put_if_set(body, "description", description)
        if tags is not None:
            body["tags"] = check_strings("tags", tags)
        answer = await self._request("POST", "/v1/recipe-box", json_body=body)
        return RecipeSummary.from_dict(as_mapping(answer.data))

    async def import_recipe(self, url: str) -> ImportedRecipe:
        """Download the recipe on a web page and add it to the recipe box.

        A page the API cannot read a recipe from raises `RecipeImportFailedError`, whose
        `reason` says why. A recipe downloader that is down or slow raises `UnavailableError`.
        """
        answer = await self._request("POST", "/v1/recipe-box/import", json_body={"url": url})
        return ImportedRecipe(
            recipe=RecipeSummary.from_dict(as_mapping(answer.data)),
            created=answer.status == 201,
        )

    async def delete_recipe(self, recipe_id: str) -> None:
        """Remove a recipe from the recipe box. It cannot be undone.

        A recipe with a meal in the active meal plan raises `ConflictError`, so remove the meal
        first. A recipe whose meal the user cooked within the last few days can raise it too.
        """
        await self._request("DELETE", f"/v1/recipe-box/{_id('recipe_id', recipe_id)}")

    # Active meal plan

    async def get_active_meal_plan(self, *, include_ingredients: bool = False) -> list[Meal]:
        """Return the meals the user plans to cook and has not cooked yet."""
        params: list[tuple[str, str]] = []
        _include(params, ingredients=include_ingredients)
        answer = await self._request("GET", "/v1/meal-plans/active", params=params)
        return get_objects(as_mapping(answer.data), "meals", Meal.from_dict)

    async def add_meals(self, meals: Sequence[NewMeal]) -> list[Meal]:
        """Plan from 1 to 20 meals, and add each meal's ingredients to a shopping list.

        The meals may hold at most 200 ingredients together. The call returns one meal per
        entry, in order. It checks every meal before it adds any. When the list fills up
        partway, it raises `LimitReachedError`, and `added_meals` lists every meal it planned.
        """
        answer = await self._request(
            "POST",
            "/v1/meal-plans/active/meals",
            json_body={"meals": [meal.to_dict() for meal in meals]},
        )
        return get_objects(as_mapping(answer.data), "meals", Meal.from_dict)

    async def change_meal(
        self,
        meal_id: str,
        *,
        portions: str | None = None,
        occasion: str | None = None,
        is_purchased: bool | None = None,
        is_cooked: bool | None = None,
    ) -> Meal:
        """Change a planned meal and return it. The call must change at least one field.

        Each argument has rules of its own:

        - New `portions` also scale what the API added to the list for the meal. A larger
          count can fill the list, which raises `LimitReachedError` after a partial change.
        - An empty `occasion` clears it.
        - `is_purchased` and `is_cooked` take only True.
        - `is_cooked` cannot be combined with another field. A cooked meal leaves the plan.
        """
        body: dict[str, Any] = {}
        _put_if_set(body, "portions", portions)
        _put_if_set(body, "occasion", occasion)
        _put_if_set(body, "isPurchased", is_purchased)
        _put_if_set(body, "isCooked", is_cooked)
        answer = await self._request(
            "PATCH", f"/v1/meal-plans/active/meals/{_id('meal_id', meal_id)}", json_body=body
        )
        return Meal.from_dict(as_mapping(answer.data))

    async def remove_meal(self, meal_id: str) -> None:
        """Remove a meal from the plan, and take back what the API added to the list for it.

        The recipe stays in the recipe box.
        """
        await self._request("DELETE", f"/v1/meal-plans/active/meals/{_id('meal_id', meal_id)}")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Sequence[tuple[str, str]] | None = None,
        json_body: Mapping[str, Any] | None = None,
        etag: str | None = None,
    ) -> _Answer:
        headers = {"Accept": "application/json"}
        if etag is not None:
            headers["If-None-Match"] = etag
        kwargs: dict[str, Any] = {"headers": headers}
        if params:
            kwargs["params"] = list(params)
        if json_body is not None:
            kwargs["json"] = json_body

        access_token = await self._auth.async_get_access_token()
        try:
            async with asyncio.timeout(self._request_timeout):
                response = await self._auth.send(method, path, access_token, **kwargs)
                try:
                    body = await response.read()
                finally:
                    response.release()
        except TimeoutError as err:
            raise AlacartConnectionError(f"{method} {path} timed out") from err
        except ClientError as err:
            raise AlacartConnectionError(f"{method} {path} failed: {err}") from err

        if response.status >= 400:
            raise _error(response.status, response.headers, body)
        if 300 <= response.status < 400 and response.status != 304:
            raise AlacartResponseError(
                f"{method} {path} answered with the redirect {response.status}, "
                "which the library does not follow"
            )
        if response.status == 304 and etag is None:
            raise AlacartResponseError(f"{method} {path} answered 304 to a request without an ETag")
        if response.status in (204, 304):
            return _Answer(response.status, response.headers, None)
        try:
            data = json.loads(body)
        except ValueError as err:
            raise AlacartResponseError(f"{method} {path} answered with invalid JSON") from err
        return _Answer(response.status, response.headers, data)


def _error(status: int, headers: Mapping[str, str], body: bytes) -> AlacartApiError:
    problem: Mapping[str, Any] = {}
    try:
        parsed = json.loads(body) if body else None
    except ValueError:
        parsed = None
    if isinstance(parsed, Mapping):
        problem = parsed

    code = problem.get("code")
    code = code if isinstance(code, str) else None
    error_class = _ERRORS_BY_CODE.get(code or "") or _ERRORS_BY_STATUS.get(status)
    if error_class is None:
        error_class = ServerError if status >= 500 else AlacartApiError

    detail = problem.get("detail")
    title = problem.get("title")
    type_url = problem.get("type")
    common: dict[str, Any] = {
        "title": title if isinstance(title, str) else None,
        "type_url": type_url if isinstance(type_url, str) else None,
        "problem": problem,
    }
    detail = detail if isinstance(detail, str) else None

    if issubclass(error_class, RetryLaterError):
        return error_class(status, code, detail, retry_after=_retry_after(headers), **common)
    if issubclass(error_class, LimitReachedError):
        return error_class(
            status,
            code,
            detail,
            added_items=_partial(problem, "items", AddedItem.from_dict),
            added_meals=_partial(problem, "meals", Meal.from_dict),
            **common,
        )
    return error_class(status, code, detail, **common)


def _partial[T](
    problem: Mapping[str, Any], key: str, parse: Callable[[Mapping[str, Any]], T]
) -> list[T]:
    # The entries a call added before the list filled up are useful but not essential, so a
    # malformed list does not hide the error itself.
    if key not in problem:
        return []
    try:
        return get_objects(problem, key, parse)
    except AlacartResponseError:
        return []


def _retry_after(headers: Mapping[str, str]) -> int | None:
    # The API always sends a number of seconds, never the HTTP-date form that HTTP also allows.
    value = headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(0, int(value))
    except ValueError:
        return None


def _texts(data: Mapping[str, Any], key: str) -> list[str]:
    return get_objects(data, key, lambda entry: get_str(entry, "text"))


def _id(name: str, value: str) -> str:
    # Ids are opaque text, so a character such as a slash must not change the path.
    return quote(check_id(name, value), safe="")


def _put_if_set(body: dict[str, Any], key: str, value: Any) -> None:
    if value is not None:
        body[key] = value


def _param_if_set(params: list[tuple[str, str]], key: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, bool):
        params.append((key, "true" if value else "false"))
    else:
        params.append((key, str(value)))


def _include(params: list[tuple[str, str]], **fields: bool) -> None:
    names = [name for name, wanted in fields.items() if wanted]
    if names:
        params.append(("include", ",".join(names)))
