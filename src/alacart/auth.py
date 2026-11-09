"""Authentication for the Alacart API.

The library never signs a user in. The app signs in through OAuth 2.0 with PKCE, keeps the tokens,
and gives the client an `AbstractAuth` that returns a valid access token for each request.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from aiohttp import ClientResponse, ClientSession
from yarl import URL

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


class AbstractAuth(ABC):
    """Makes authenticated requests to the Alacart API.

    Subclass it and implement `async_get_access_token`. The subclass refreshes the token when it
    has expired, so the method always returns one that works.
    """

    def __init__(self, websession: ClientSession, host: str) -> None:
        """Set up requests to the API at `host`.

        `host` is the API's address without a path, such as `alacart.API_URL`. It must use HTTPS,
        except on the loopback address, because every request carries the user's token. The
        session's owner closes it. The library never does.
        """
        url = URL(host)
        if url.scheme != "https" and not (url.scheme == "http" and url.host in _LOOPBACK_HOSTS):
            raise ValueError(f"The API host must use HTTPS: {host}")
        if not url.host or url.user or url.password or url.path not in ("", "/"):
            raise ValueError(f"The API host must be an address without a path: {host}")
        if url.query_string or url.fragment:
            raise ValueError(f"The API host must be an address without a path: {host}")
        self.websession = websession
        self.host = str(url.origin())

    @abstractmethod
    async def async_get_access_token(self) -> str:
        """Return a valid access token.

        The client lets every exception from this method reach its caller unchanged. A refresh
        that fails because the user revoked the app should raise something the app can tell from
        a network failure, so the app can ask the user to sign in again.
        """

    async def send(
        self, method: str, path: str, access_token: str, **kwargs: Any
    ) -> ClientResponse:
        """Send a request to `path` under the host, with the given access token.

        `AlacartClient` calls it after `async_get_access_token`. `path` starts with a slash, such
        as `/v1/items`. The keyword arguments go to `ClientSession.request`. The request never
        follows a redirect, so the token never goes to another address. The caller reads the
        response and releases it.
        """
        kwargs.pop("allow_redirects", None)
        headers = dict(kwargs.pop("headers", None) or {})
        headers["Authorization"] = f"Bearer {access_token}"
        return await self.websession.request(
            method, f"{self.host}{path}", headers=headers, allow_redirects=False, **kwargs
        )


class StaticTokenAuth(AbstractAuth):
    """Sends the same access token on every request.

    It suits a short script. An access token lives 60 minutes, so a program that runs longer
    needs an `AbstractAuth` that refreshes it.
    """

    def __init__(self, websession: ClientSession, host: str, access_token: str) -> None:
        super().__init__(websession, host)
        self._access_token = access_token

    async def async_get_access_token(self) -> str:
        return self._access_token
