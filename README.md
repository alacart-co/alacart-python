# alacart

`alacart` is an async Python client for version 1 of the Alacart public API. It reads and changes
a user's shopping lists, items, recipe box and meal plan, on behalf of a user who has signed in to
your app. The Alacart integration for Home Assistant uses it, and any other Python app can too.

The API serves only premium accounts. Every call from an account without premium raises
`PremiumRequiredError`.

## API hosts

The API runs in beta today, at `https://api.test.alacart.io`, with its sign-in server at
`https://auth.test.alacart.io`. Beta holds test data, and it is where you build and test an app.
Production will serve the API at `https://api.alacart.io`, with sign-in at
`https://auth.alacart.io`, once the API launches there. The library names the four addresses
`BETA_API_URL`, `BETA_AUTH_URL`, `API_URL` and `AUTH_URL`.

The API's reference and guides are at <https://api.test.alacart.io/docs>.

To build an app, you need an account with premium in beta. Until the API launches in production,
Alacart gives beta premium by hand to the developers it invites.

## Installing

```sh
pip install alacart
```

The library needs Python 3.12 or later, `aiohttp` and `yarl`.

## Signing in

The library does not sign users in. Your app signs the user in through the OAuth 2.0
authorization code flow with Proof Key for Code Exchange (PKCE), and keeps the tokens. It gives
the client an `AbstractAuth`, which the client asks for an access token before each call.

- Register your app on beta's developer page at <https://www.test.matlistan.se/developer/apps>
  to get a client id. The page lives in the web app where Swedish users sign in. A client id
  from beta works only against beta, and production gets a developer page of its own when the
  API launches there.
- On the developer page, you choose whether the app is public or confidential. An app that runs
  on the user's own device, such as Home Assistant, is public, because it cannot keep a secret.
  An app that runs on your own server can be confidential. A confidential app gets a client
  secret, which the page shows once.
- A redirect URI may be a loopback URI such as `http://127.0.0.1/callback`, a URI with your app's
  own scheme, or an HTTPS URI on any host.
- The authorization endpoint is `/connect/authorize` on the sign-in server, and the token
  endpoint is `/connect/token`. The library names the paths `AUTHORIZE_PATH` and `TOKEN_PATH`.
- Every app sends a PKCE code challenge with the `S256` method. A confidential app also sends
  its client secret to the token endpoint, with HTTP Basic authentication or in the form body.
- Ask for the scope `read`, or `read write` when your app changes anything. The user sees the
  choice on the consent page.
- An access token lives 60 minutes. To refresh it, post `grant_type=refresh_token` with the
  refresh token to the token endpoint. Each refresh returns a new refresh token, which lives 90
  days, and the app uses the new one from then on.
- To sign the user out of your app, post the refresh token as the form field `token` to the
  revocation endpoint, `/connect/revoke`, which the library names `REVOKE_PATH`. A confidential
  app authenticates there as it does at the token endpoint.

Beta also has a client for testing, with the client id `alacart-test`. Its redirect URI is
`http://127.0.0.1/callback`, and the sign-in server accepts that URI on any port. A script on your
own computer can then catch the code. [`examples/sign_in_beta.py`](examples/sign_in_beta.py) signs
in that way and lists the user's shopping lists. Run it with `--print-token` to get an access
token for the `StaticTokenAuth` example under *Using the client*.

## Using the client

Pass the client an `AbstractAuth` that knows the API's address and returns a valid access token.
A short script can use `StaticTokenAuth`, which sends the same token on every call:

```python
import asyncio

import aiohttp

from alacart import BETA_API_URL, AlacartClient, StaticTokenAuth


async def main(access_token: str) -> None:
    async with aiohttp.ClientSession() as session:
        client = AlacartClient(StaticTokenAuth(session, BETA_API_URL, access_token))
        await client.add_items(["2 l mjölk", "bröd"])
        result = await client.get_items()
        for item in result.items:
            print(item.text, "(checked)" if item.is_checked else "")


asyncio.run(main("<access token>"))
```

A program that runs for longer than an hour must refresh the token. Subclass `AbstractAuth`, and
make `async_get_access_token` return a token that has not expired:

```python
from aiohttp import ClientSession

from alacart import AbstractAuth


class MyAuth(AbstractAuth):
    def __init__(self, session: ClientSession, host: str, tokens: "MyTokenStore") -> None:
        super().__init__(session, host)
        self._tokens = tokens

    async def async_get_access_token(self) -> str:
        await self._tokens.refresh_if_expired()
        return self._tokens.access_token
```

The client lets every exception from `async_get_access_token` reach your code unchanged. When the
user has revoked your app, raise an exception there that your app can tell from a network
failure. Your app then knows to ask the user to sign in again. The client never closes the
session, so the code that created it closes it.

A call times out after 30 seconds, counted from sending the request to reading the whole answer.
Pass `request_timeout` to `AlacartClient` to change the limit.

## Polling with ETags

`get_items` and `get_item_lists` return the answer's ETag. Pass it to the next call with the same
arguments, and the call returns `None` when nothing has changed. An unchanged answer costs the API
less. It still counts against the rate limit.

The rate limit allows each signed-in user 60 requests a minute through each app. The API may lower
it, so poll no more often than your app needs. A request over the limit raises
`RateLimitedError`.

```python
latest = await client.get_items()
...
changed = await client.get_items(etag=latest.etag)
if changed is not None:
    latest = changed
```

## Errors

When the API answers with an error, the client raises `AlacartApiError` or one of its subclasses.
The API's error answers are problem responses, JSON bodies of the type `application/problem+json`
that RFC 9457 defines. The exception's `code` and `detail` come from that body, and its `status`
holds the HTTP status.

| Exception | API code | Meaning |
| --- | --- | --- |
| `InvalidRequestError` | `invalid_request` | A parameter or body field is wrong. `errors` says what is wrong with each field. |
| `InvalidTokenError` | `invalid_token` | The token is missing, expired or revoked. Sign the user in again. |
| `InsufficientScopeError` | `insufficient_scope` | The user allowed reading only. Ask the user to sign in again with the scopes `read write`. |
| `PremiumRequiredError` | `premium_required` | The account has no premium. Signing in again does not help. |
| `NotFoundError` | `not_found` | The id does not exist, or it belongs to another user. |
| `ConflictError` | `conflict` | The change clashes with existing data, such as a second list with the same name. |
| `LimitReachedError` | `limit_reached` | The list is full. `added_items` or `added_meals` lists what the call did add. |
| `RecipeImportFailedError` | `recipe_import_failed` | `reason` says why the page gave no recipe. |
| `RateLimitedError` | `rate_limited` | The app sent too many requests. Wait `retry_after` seconds. |
| `UnavailableError` | `unavailable` | A service that the call needs is down or slow. Wait `retry_after` seconds. |
| `ServerError` | `server_error` | The API failed. Try again later. |

A call that adds several entries can fill the list partway, and then raises `LimitReachedError`.
From `add_items`, its `added_items` lists the items added before the list filled up. From
`add_meals`, its `added_meals` lists every meal the call planned, including the meal whose
ingredients filled the list.

An answer without a code that the library knows raises the class for its HTTP status:

- 401 raises `InvalidTokenError`, and 404 raises `NotFoundError`.
- 429 raises `RateLimitedError`, and 503 raises `UnavailableError`.
- Any other status from 500 up raises `ServerError`.
- Any other status raises `AlacartApiError` itself.

When the library cannot reach the API, or the API does not answer in time, it raises
`AlacartConnectionError`. After that error or a `ServerError`, a call that changes data may have
gone through anyway. Read the data again before you repeat the call, or an item can end up added
twice. An answer the library cannot read raises `AlacartResponseError`. All of
them derive from `AlacartError`.

## Methods and endpoints

Each method of `AlacartClient` calls one endpoint of the API:

| Method | Endpoint |
| --- | --- |
| `get_me` | `GET /v1/me` |
| `get_stores` | `GET /v1/stores` |
| `get_item_lists` | `GET /v1/item-lists` |
| `create_item_list` | `POST /v1/item-lists` |
| `change_item_list` | `PATCH /v1/item-lists/{listId}` |
| `delete_item_list` | `DELETE /v1/item-lists/{listId}` |
| `get_sorted_items` | `GET /v1/item-lists/{listId}/sorted` |
| `set_manual_order` | `PUT /v1/item-lists/{listId}/manual-order` |
| `get_items` | `GET /v1/items` |
| `add_items` | `POST /v1/items` |
| `change_item` | `PATCH /v1/items/{itemId}` |
| `remove_item` | `DELETE /v1/items/{itemId}` |
| `get_favorite_items` | `GET /v1/items/favorites` |
| `get_item_suggestions` | `GET /v1/items/suggestions` |
| `search_recipe_box` | `GET /v1/recipe-box` |
| `get_recipe` | `GET /v1/recipe-box/{recipeId}` |
| `get_recipe_ingredients` | `GET /v1/recipe-box/{recipeId}/ingredients` |
| `add_recipe` | `POST /v1/recipe-box` |
| `import_recipe` | `POST /v1/recipe-box/import` |
| `delete_recipe` | `DELETE /v1/recipe-box/{recipeId}` |
| `get_active_meal_plan` | `GET /v1/meal-plans/active` |
| `add_meals` | `POST /v1/meal-plans/active/meals` |
| `change_meal` | `PATCH /v1/meal-plans/active/meals/{mealId}` |
| `remove_meal` | `DELETE /v1/meal-plans/active/meals/{mealId}` |

Later releases of the API may add response fields and new values of fields with fixed values,
such as a meal's `type`. The library ignores fields it does not know. It keeps fields with fixed
values as plain strings, so a new value does not break your app.

## Developing

Install the library with its development tools, and run the checks. The `--group` option needs
pip 25.1 or later.

```sh
pip install -e . --group dev
ruff format --check .
ruff check .
mypy
pytest
```

The tests answer each call with a fixture from `tests/fixtures`. A test checks every fixture
against the API's own OpenAPI document, kept in `tests/openapi.v1.json`. When the API changes,
replace that copy with the one beta serves at `https://api.test.alacart.io/openapi/v1.json`.

## Releasing

GitHub Actions publishes each release to PyPI through PyPI's trusted publishing, so the
repository holds no PyPI token. PyPI's publisher for the project names this repository, the
workflow `release.yml` and the GitHub environment `pypi`.

1. Set the new version in `pyproject.toml`, and merge the change to `main`.
2. Create a GitHub release whose tag is the version with a `v` in front, such as `v0.1.0`.

The workflow `.github/workflows/release.yml` refuses a tag that does not match the version in
`pyproject.toml`, and a tag on a commit that is not on `main`. It also refuses a GitHub
pre-release whose version is final, such as `0.2.0`, and a full release whose version is a
pre-release, such as `0.2.0b1`. It runs every check of the CI workflow before it builds and
publishes.

## License

The library is licensed under the Apache License 2.0. See [LICENSE](LICENSE).
