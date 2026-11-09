"""Tests of the calls that fail."""

from __future__ import annotations

import asyncio

import aiohttp
import pytest

from alacart import (
    AbstractAuth,
    AlacartApiError,
    AlacartClient,
    AlacartConnectionError,
    AlacartResponseError,
    ConflictError,
    InsufficientScopeError,
    InvalidRequestError,
    InvalidTokenError,
    LimitReachedError,
    NewMeal,
    NotFoundError,
    PremiumRequiredError,
    RateLimitedError,
    RecipeImportFailedError,
    RecipeImportFailure,
    RetryLaterError,
    ServerError,
    StaticTokenAuth,
    UnavailableError,
)

from .conftest import FakeApi, load_fixture


@pytest.mark.parametrize(
    ("fixture", "error_class"),
    [
        ("problem_invalid_token", InvalidTokenError),
        ("problem_premium_required", PremiumRequiredError),
        ("problem_not_found", NotFoundError),
        ("problem_conflict", ConflictError),
    ],
)
async def test_each_code_raises_its_class(
    client: AlacartClient, api: FakeApi, fixture: str, error_class: type[AlacartApiError]
) -> None:
    problem = load_fixture(fixture)
    api.problem("GET", "/v1/me", fixture)

    with pytest.raises(error_class) as caught:
        await client.get_me()

    assert caught.value.status == problem["status"]
    assert caught.value.code == problem["code"]
    assert caught.value.detail == problem["detail"]
    assert caught.value.title == problem["title"]
    assert caught.value.type_url == problem["type"]
    assert str(caught.value) == problem["detail"]


async def test_invalid_request_lists_the_wrong_fields(client: AlacartClient, api: FakeApi) -> None:
    api.problem("POST", "/v1/items", "problem_invalid_request")

    with pytest.raises(InvalidRequestError) as caught:
        await client.add_items(["a", "b", "c" * 201])

    assert caught.value.errors == {"texts[2]": ["The text must be at most 200 characters."]}


async def test_limit_reached_lists_the_items_added_before(
    client: AlacartClient, api: FakeApi
) -> None:
    api.problem("POST", "/v1/items", "problem_limit_reached_items")

    with pytest.raises(LimitReachedError) as caught:
        await client.add_items(["ägg", "smör"])

    assert caught.value.limit == 500
    assert [added.item.text for added in caught.value.added_items] == ["ägg"]
    assert caught.value.added_meals == []


async def test_limit_reached_lists_the_meals_planned_before(
    client: AlacartClient, api: FakeApi
) -> None:
    api.problem("POST", "/v1/meal-plans/active/meals", "problem_limit_reached_meals")

    with pytest.raises(LimitReachedError) as caught:
        await client.add_meals([NewMeal(recipe_id="5502", ingredients=["linser"])])

    assert [meal.id for meal in caught.value.added_meals] == ["3303"]


async def test_limit_reached_with_malformed_entries_still_raises(
    client: AlacartClient, api: FakeApi
) -> None:
    problem = {**load_fixture("problem_limit_reached_items"), "items": [{"id": "1"}]}
    api.answer("POST", "/v1/items", status=409, json_body=problem)

    with pytest.raises(LimitReachedError) as caught:
        await client.add_items(["ägg"])

    assert caught.value.limit == 500
    assert caught.value.added_items == []


async def test_recipe_import_failed_gives_the_reason(client: AlacartClient, api: FakeApi) -> None:
    api.problem("POST", "/v1/recipe-box/import", "problem_recipe_import_failed")

    with pytest.raises(RecipeImportFailedError) as caught:
        await client.import_recipe("https://example.com/recept")

    assert caught.value.reason == RecipeImportFailure.SITE_NOT_SUPPORTED


@pytest.mark.parametrize(
    ("fixture", "error_class"),
    [("problem_rate_limited", RateLimitedError), ("problem_unavailable", UnavailableError)],
)
async def test_retry_after_is_read(
    client: AlacartClient, api: FakeApi, fixture: str, error_class: type[RetryLaterError]
) -> None:
    api.problem("GET", "/v1/me", fixture, headers={"Retry-After": "30"})

    with pytest.raises(error_class) as caught:
        await client.get_me()

    assert caught.value.retry_after == 30


async def test_an_answer_without_a_problem_body_raises_by_status(
    client: AlacartClient, api: FakeApi
) -> None:
    api.answer("GET", "/v1/me", status=429, body="<html>Too many</html>", content_type="text/html")
    api.answer("GET", "/v1/stores", status=502, body="<html>Bad gateway</html>")

    with pytest.raises(RateLimitedError) as rate_limited:
        await client.get_me()
    with pytest.raises(ServerError) as server_error:
        await client.get_stores()

    assert rate_limited.value.code is None
    assert rate_limited.value.retry_after is None
    assert server_error.value.status == 502


async def test_an_unknown_code_raises_the_base_class(client: AlacartClient, api: FakeApi) -> None:
    problem = {**load_fixture("problem_conflict"), "code": "teapot", "status": 418}
    api.answer("GET", "/v1/me", status=418, json_body=problem)

    with pytest.raises(AlacartApiError) as caught:
        await client.get_me()

    assert type(caught.value) is AlacartApiError
    assert caught.value.code == "teapot"


async def test_an_unreachable_api_raises_connection_error(
    session: aiohttp.ClientSession,
) -> None:
    # Nothing listens on port 9 of the loopback address, so the connection is refused.
    client = AlacartClient(StaticTokenAuth(session, "http://127.0.0.1:9", "t"))

    with pytest.raises(AlacartConnectionError):
        await client.get_me()


async def test_a_slow_answer_raises_connection_error(
    api: FakeApi, session: aiohttp.ClientSession
) -> None:
    api.answer("GET", "/v1/me", json_body=load_fixture("me"), delay=1)
    client = AlacartClient(StaticTokenAuth(session, api.base_url, "t"), request_timeout=0.05)

    with pytest.raises(AlacartConnectionError, match="timed out"):
        await client.get_me()


async def test_invalid_json_raises_response_error(client: AlacartClient, api: FakeApi) -> None:
    api.answer("GET", "/v1/me", body="{not json")

    with pytest.raises(AlacartResponseError):
        await client.get_me()


async def test_a_missing_field_raises_response_error(client: AlacartClient, api: FakeApi) -> None:
    me = load_fixture("me")
    del me["isFamilyPremium"]
    api.answer("GET", "/v1/me", json_body=me)

    with pytest.raises(AlacartResponseError, match="isFamilyPremium"):
        await client.get_me()


async def test_a_wrong_type_raises_response_error(client: AlacartClient, api: FakeApi) -> None:
    api.answer("GET", "/v1/items", json_body={"items": [{**load_fixture("item"), "addedAt": 5}]})

    with pytest.raises(AlacartResponseError, match="addedAt"):
        await client.get_items()


@pytest.mark.parametrize(
    ("code", "status", "error_class"),
    [
        ("insufficient_scope", 403, InsufficientScopeError),
        ("server_error", 500, ServerError),
    ],
)
async def test_other_codes_raise_their_class(
    client: AlacartClient,
    api: FakeApi,
    code: str,
    status: int,
    error_class: type[AlacartApiError],
) -> None:
    problem = {**load_fixture("problem_conflict"), "code": code, "status": status}
    api.answer("GET", "/v1/me", status=status, json_body=problem)

    with pytest.raises(error_class):
        await client.get_me()


async def test_odd_errors_members_do_not_break_the_error(
    client: AlacartClient, api: FakeApi
) -> None:
    problem = {
        **load_fixture("problem_invalid_request"),
        "errors": {"name": "Too long.", "texts": 5, "listId": ["Unknown."]},
    }
    api.answer("POST", "/v1/items", status=400, json_body=problem)

    with pytest.raises(InvalidRequestError) as caught:
        await client.add_items(["a"])

    assert caught.value.errors == {"name": ["Too long."], "listId": ["Unknown."]}


async def test_a_failing_token_refresh_reaches_the_caller_unchanged(
    api: FakeApi, session: aiohttp.ClientSession
) -> None:
    class RevokedError(Exception):
        pass

    class FailingAuth(AbstractAuth):
        async def async_get_access_token(self) -> str:
            raise RevokedError

    client = AlacartClient(FailingAuth(session, api.base_url))

    with pytest.raises(RevokedError):
        await client.get_me()
    assert api.requests == []


async def test_a_stalled_body_raises_connection_error(
    api: FakeApi, session: aiohttp.ClientSession
) -> None:
    api.answer("GET", "/v1/me", json_body=load_fixture("me"), body_delay=1)
    client = AlacartClient(StaticTokenAuth(session, api.base_url, "t"), request_timeout=0.1)

    with pytest.raises(AlacartConnectionError, match="timed out"):
        await client.get_me()


async def test_a_304_without_an_etag_raises_response_error(
    client: AlacartClient, api: FakeApi
) -> None:
    api.answer("GET", "/v1/items", status=304)

    with pytest.raises(AlacartResponseError):
        await client.get_items()


async def test_redirects_are_not_followed(client: AlacartClient, api: FakeApi) -> None:
    api.answer("GET", "/v1/me", status=302, headers={"Location": "https://example.com/steal"})

    with pytest.raises(AlacartResponseError, match="redirect"):
        await client.get_me()

    assert len(api.requests) == 1


@pytest.mark.parametrize("item_id", ["", ".", ".."])
async def test_ids_that_would_change_the_path_are_refused(
    client: AlacartClient, api: FakeApi, item_id: str
) -> None:
    with pytest.raises(ValueError, match="not an id"):
        await client.remove_item(item_id)

    assert api.requests == []


async def test_an_id_that_is_not_a_string_is_refused(client: AlacartClient) -> None:
    with pytest.raises(TypeError, match="must be a string"):
        await client.remove_item(77003)  # type: ignore[arg-type]


async def test_a_single_string_where_a_list_belongs_is_refused(
    client: AlacartClient, api: FakeApi
) -> None:
    with pytest.raises(TypeError, match="texts"):
        await client.add_items("mjölk")
    with pytest.raises(TypeError, match="tags"):
        await client.search_recipe_box(tags="snabbt")
    with pytest.raises(TypeError, match="ingredients"):
        await client.add_meals([NewMeal(recipe_id="1", ingredients="mjölk")])  # type: ignore[arg-type]

    assert api.requests == []


def test_a_host_without_https_is_refused(session: aiohttp.ClientSession) -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        StaticTokenAuth(session, "http://api.alacart.io", "t")


@pytest.mark.parametrize(
    "error", [RuntimeError("revoked"), aiohttp.ClientConnectionError("down"), TimeoutError()]
)
async def test_every_token_failure_reaches_the_caller_unchanged(
    api: FakeApi, session: aiohttp.ClientSession, error: Exception
) -> None:
    class FailingAuth(AbstractAuth):
        async def async_get_access_token(self) -> str:
            raise error

    client = AlacartClient(FailingAuth(session, api.base_url))

    with pytest.raises(type(error)) as caught:
        await client.get_me()

    assert caught.value is error
    assert api.requests == []


async def test_the_timeout_leaves_out_the_time_to_get_a_token(
    api: FakeApi, session: aiohttp.ClientSession
) -> None:
    class SlowAuth(AbstractAuth):
        async def async_get_access_token(self) -> str:
            await asyncio.sleep(0.2)
            return "t"

    api.answer("GET", "/v1/me", json_body=load_fixture("me"))
    client = AlacartClient(SlowAuth(session, api.base_url), request_timeout=0.1)

    me = await client.get_me()

    assert me.id == "481516"


async def test_a_timed_out_answer_does_not_block_the_next_call(api: FakeApi) -> None:
    # With one connection allowed, the second call can only start once the first call's
    # half-read connection has been freed. aiohttp frees it when the read is cancelled, so the
    # test pins the behavior a caller sees, not the client's own release of the response.
    api.answer("GET", "/v1/me", json_body=load_fixture("me"), body_delay=1)
    api.answer("GET", "/v1/me", json_body=load_fixture("me"))
    connector = aiohttp.TCPConnector(limit=1)
    async with aiohttp.ClientSession(connector=connector) as session:
        client = AlacartClient(StaticTokenAuth(session, api.base_url, "t"), request_timeout=0.2)
        with pytest.raises(AlacartConnectionError):
            await client.get_me()

        me = await client.get_me()

    assert me.id == "481516"


async def test_cancelling_a_call_cancels_it(api: FakeApi, client: AlacartClient) -> None:
    api.answer("GET", "/v1/me", json_body=load_fixture("me"), delay=1)
    task = asyncio.create_task(client.get_me())
    await asyncio.sleep(0.05)

    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.parametrize(
    ("status", "error_class"),
    [
        (401, InvalidTokenError),
        (404, NotFoundError),
        (429, RateLimitedError),
        (503, UnavailableError),
        (500, ServerError),
        (400, AlacartApiError),
    ],
)
async def test_an_unknown_code_raises_the_class_for_its_status(
    client: AlacartClient, api: FakeApi, status: int, error_class: type[AlacartApiError]
) -> None:
    problem = {**load_fixture("problem_conflict"), "code": "something_new", "status": status}
    api.answer("GET", "/v1/me", status=status, json_body=problem)

    with pytest.raises(AlacartApiError) as caught:
        await client.get_me()

    assert type(caught.value) is error_class
    assert caught.value.code == "something_new"


@pytest.mark.parametrize(("header", "seconds"), [("-5", 0), ("1.5", None), ("soon", None)])
async def test_odd_retry_after_values(
    client: AlacartClient, api: FakeApi, header: str, seconds: int | None
) -> None:
    api.problem("GET", "/v1/me", "problem_rate_limited", headers={"Retry-After": header})

    with pytest.raises(RateLimitedError) as caught:
        await client.get_me()

    assert caught.value.retry_after == seconds


@pytest.mark.parametrize("status", [301, 303, 307, 308])
async def test_no_redirect_is_followed(client: AlacartClient, api: FakeApi, status: int) -> None:
    api.answer("GET", "/v1/me", status=status, headers={"Location": "/v1/stores"})

    with pytest.raises(AlacartResponseError, match="redirect"):
        await client.get_me()

    assert [request.path for request in api.requests] == ["/v1/me"]


async def test_ids_in_bodies_and_queries_are_checked(client: AlacartClient, api: FakeApi) -> None:
    with pytest.raises(TypeError, match="list_id"):
        await client.add_items(["mjölk"], list_id=9001)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="list_id"):
        await client.get_items(list_id=9001)  # type: ignore[call-overload]
    with pytest.raises(TypeError, match="store_id"):
        await client.get_sorted_items("9001", 2342)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="item_ids"):
        await client.set_manual_order("9001", [1, 2])  # type: ignore[list-item]
    with pytest.raises(ValueError, match="recipe_id"):
        await client.add_meals([NewMeal(recipe_id="..", ingredients=[])])

    assert api.requests == []


async def test_a_timestamp_without_a_time_zone_raises_response_error(
    client: AlacartClient, api: FakeApi
) -> None:
    item = {**load_fixture("item"), "addedAt": "2026-11-08T09:12:45"}
    api.answer("GET", "/v1/items", json_body={"items": [item]})

    with pytest.raises(AlacartResponseError, match="time zone"):
        await client.get_items()


@pytest.mark.parametrize(
    "host",
    [
        "http://localhost.evil.com",
        "http://127.0.0.1@evil.com",
        "https://",
        "https://user:secret@api.alacart.io",
        "https://api.alacart.io/v1",
        "https://api.alacart.io?x=1",
        "ftp://api.alacart.io",
    ],
)
def test_a_bad_host_is_refused(session: aiohttp.ClientSession, host: str) -> None:
    with pytest.raises(ValueError, match="host"):
        StaticTokenAuth(session, host, "t")


@pytest.mark.parametrize(
    "host", ["https://api.alacart.io", "HTTPS://api.alacart.io/", "http://[::1]:8080"]
)
def test_a_good_host_is_accepted(session: aiohttp.ClientSession, host: str) -> None:
    StaticTokenAuth(session, host, "t")


@pytest.mark.parametrize("timeout", [0, -1])
def test_a_timeout_must_be_positive(session: aiohttp.ClientSession, timeout: float) -> None:
    with pytest.raises(ValueError, match="request_timeout"):
        AlacartClient(
            StaticTokenAuth(session, "https://api.alacart.io", "t"), request_timeout=timeout
        )
