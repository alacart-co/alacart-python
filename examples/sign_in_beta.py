"""Sign in to the Alacart beta and list the user's shopping lists.

The script uses beta's test client `alacart-test`, whose redirect URI is
`http://127.0.0.1/callback` on any port. It runs the OAuth 2.0 authorization code flow with PKCE:

1. It listens on a free port of the loopback address.
2. It opens the sign-in page in your browser, where you sign in and approve the app.
3. The sign-in server sends your browser back to the script with a code.
4. The script trades the code for an access token, and calls the API with it.

Run it with `python examples/sign_in_beta.py`. Add `--write` to ask for the `write` scope, and
`--print-token` to print the access token for your own experiments. Treat a printed token like a
password, because it reads the account's data for the next 60 minutes.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import secrets
import webbrowser
from urllib.parse import urlencode

import aiohttp
from aiohttp import web

from alacart import (
    AUTHORIZE_PATH,
    BETA_API_URL,
    BETA_AUTH_URL,
    SCOPE_READ,
    SCOPE_WRITE,
    TOKEN_PATH,
    AlacartClient,
    StaticTokenAuth,
)

CLIENT_ID = "alacart-test"
SIGN_IN_TIMEOUT = 300
"""How many seconds the script waits for you to sign in."""


async def sign_in(session: aiohttp.ClientSession, scope: str) -> str:
    """Sign the user in through their browser, and return an access token."""
    state = secrets.token_urlsafe(16)
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    received: asyncio.Future[str] = asyncio.get_running_loop().create_future()

    async def callback(request: web.Request) -> web.Response:
        if request.query.get("state") != state or received.done():
            return web.Response(status=400, text="The sign-in answer does not match this script.")
        if "error" in request.query:
            message = request.query.get("error_description") or request.query["error"]
            received.set_exception(RuntimeError(f"The sign-in failed: {message}"))
            return web.Response(text="The sign-in failed. See the terminal.")
        code = request.query.get("code")
        if not code:
            received.set_exception(RuntimeError("The sign-in answer has no code."))
            return web.Response(status=400, text="The sign-in answer has no code.")
        received.set_result(code)
        return web.Response(text="You are signed in. You can close this tab.")

    app = web.Application()
    app.router.add_get("/callback", callback)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        redirect_uri = f"http://127.0.0.1:{runner.addresses[0][1]}/callback"
        authorize_url = f"{BETA_AUTH_URL}{AUTHORIZE_PATH}?" + urlencode(
            {
                "response_type": "code",
                "client_id": CLIENT_ID,
                "redirect_uri": redirect_uri,
                "scope": scope,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        print(f"Sign in at this address, if your browser does not open it:\n\n{authorize_url}\n")
        webbrowser.open(authorize_url)
        async with asyncio.timeout(SIGN_IN_TIMEOUT):
            code = await received
    finally:
        await runner.cleanup()

    async with session.post(
        f"{BETA_AUTH_URL}{TOKEN_PATH}",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": CLIENT_ID,
            "code_verifier": verifier,
        },
    ) as response:
        text = await response.text()
    if response.status != 200:
        raise RuntimeError(f"The token endpoint answered {response.status}: {text}")
    access_token: str = json.loads(text)["access_token"]
    return access_token


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="ask for the write scope")
    parser.add_argument("--print-token", action="store_true", help="print the access token")
    args = parser.parse_args()
    scope = f"{SCOPE_READ} {SCOPE_WRITE}" if args.write else SCOPE_READ

    async with aiohttp.ClientSession() as session:
        access_token = await sign_in(session, scope)
        if args.print_token:
            print(f"Access token: {access_token}\n")

        client = AlacartClient(StaticTokenAuth(session, BETA_API_URL, access_token))
        me = await client.get_me()
        print(f"Signed in as {me.display_name or 'a user without a name'}.")
        lists = await client.get_item_lists()
        items = await client.get_items()
        for item_list in lists.item_lists:
            count = sum(1 for item in items.items if item.list_id == item_list.id)
            print(f"- {item_list.name}: {count} items")


if __name__ == "__main__":
    asyncio.run(main())
