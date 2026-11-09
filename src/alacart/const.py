"""Addresses of the Alacart API and its sign-in server."""

from typing import Final

API_URL: Final = "https://api.alacart.io"
"""The production API. The `/v1/` paths go after it."""

AUTH_URL: Final = "https://auth.alacart.io"
"""The production sign-in server, which issues the tokens for `API_URL`."""

BETA_API_URL: Final = "https://api.test.alacart.io"
"""The beta API, for testing an app against test data."""

BETA_AUTH_URL: Final = "https://auth.test.alacart.io"
"""The beta sign-in server, which issues the tokens for `BETA_API_URL`."""

AUTHORIZE_PATH: Final = "/connect/authorize"
"""The authorization endpoint's path on a sign-in server."""

TOKEN_PATH: Final = "/connect/token"
"""The token endpoint's path on a sign-in server."""

REVOKE_PATH: Final = "/connect/revoke"
"""The revocation endpoint's path, which signs a user out of the app."""

SCOPE_READ: Final = "read"
"""Lets the app read the user's lists, items, recipes, meal plan and stores."""

SCOPE_WRITE: Final = "write"
"""Lets the app read everything that `read` allows, and change it."""
