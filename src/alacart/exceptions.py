"""Exceptions that the Alacart client raises."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .models import AddedItem, Meal


class AlacartError(Exception):
    """Base class of every exception that the library raises."""


class AlacartConnectionError(AlacartError):
    """The API could not be reached, or it did not answer in time.

    A call that changes something may have gone through anyway. Read the data again before you
    repeat it, or an item can end up added twice.
    """


class AlacartResponseError(AlacartError):
    """The API answered with something the library cannot read."""


class AlacartApiError(AlacartError):
    """The API answered with an error.

    Every code that the library knows raises a subclass. An answer with another code, or with no
    problem body, raises the subclass for its HTTP status when one fits. Otherwise it raises this
    class itself. Apps branch on the class, or on `code`.
    """

    def __init__(
        self,
        status: int,
        code: str | None,
        detail: str | None,
        *,
        title: str | None = None,
        type_url: str | None = None,
        problem: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(detail or title or f"The API answered with status {status}")
        self.status = status
        """The HTTP status."""
        self.code = code
        """The error code, such as `not_found`, or None when the answer had no problem body."""
        self.detail = detail
        """An English sentence about this answer, for a developer to read."""
        self.title = title
        """A short English description of the code."""
        self.type_url = type_url
        """A link to the code's description in the API's errors guide."""
        self.problem: Mapping[str, Any] = problem or {}
        """The whole problem body, including members that the library does not read."""


class InvalidRequestError(AlacartApiError):
    """A parameter or body field is missing or invalid (`invalid_request`)."""

    @property
    def errors(self) -> dict[str, list[str]]:
        """What is wrong with each field, keyed by the field's name, such as `texts[2]`."""
        errors = self.problem.get("errors")
        if not isinstance(errors, Mapping):
            return {}
        result: dict[str, list[str]] = {}
        for key, value in errors.items():
            if isinstance(value, str):
                result[str(key)] = [value]
            elif isinstance(value, list):
                result[str(key)] = [str(message) for message in value]
        return result


class InvalidTokenError(AlacartApiError):
    """The token is missing, expired or revoked (`invalid_token`).

    The user has to sign in again.
    """


class InsufficientScopeError(AlacartApiError):
    """The user allowed the app to read only, and the call needs `write`."""


class PremiumRequiredError(AlacartApiError):
    """The account has no premium (`premium_required`).

    Signing in again does not help. The user has to buy premium in the Alacart app.
    """


class NotFoundError(AlacartApiError):
    """The id does not exist, or it belongs to another user (`not_found`)."""


class ConflictError(AlacartApiError):
    """The change clashes with existing data (`conflict`).

    An example is a second list with the same name as another.
    """


class LimitReachedError(AlacartApiError):
    """The list holds as many items as it may (`limit_reached`).

    A call that adds several entries can fill the list partway. `added_items` and `added_meals`
    then hold what the call added before the list filled up.
    """

    def __init__(
        self,
        status: int,
        code: str | None,
        detail: str | None,
        *,
        title: str | None = None,
        type_url: str | None = None,
        problem: Mapping[str, Any] | None = None,
        added_items: list[AddedItem] | None = None,
        added_meals: list[Meal] | None = None,
    ) -> None:
        super().__init__(status, code, detail, title=title, type_url=type_url, problem=problem)
        limit = self.problem.get("limit")
        self.limit: int | None = (
            limit if isinstance(limit, int) and not isinstance(limit, bool) else None
        )
        """The most items the list may hold."""
        self.added_items: list[AddedItem] = added_items or []
        """From `add_items`, the items added before the list filled up."""
        self.added_meals: list[Meal] = added_meals or []
        """From `add_meals`, the meals the call put in the plan, the last one included."""


class RecipeImportFailedError(AlacartApiError):
    """The API could not add the recipe on the web page (`recipe_import_failed`)."""

    @property
    def reason(self) -> str | None:
        """Why the import failed, such as `site_not_supported`. See `RecipeImportFailure`."""
        reason = self.problem.get("reason")
        return reason if isinstance(reason, str) else None


class RetryLaterError(AlacartApiError):
    """Base class of the errors that say when to try again."""

    def __init__(
        self,
        status: int,
        code: str | None,
        detail: str | None,
        *,
        title: str | None = None,
        type_url: str | None = None,
        problem: Mapping[str, Any] | None = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(status, code, detail, title=title, type_url=type_url, problem=problem)
        self.retry_after = retry_after
        """How many seconds to wait before trying again, or None when the API did not say."""


class RateLimitedError(RetryLaterError):
    """The app sent too many requests (`rate_limited`)."""


class UnavailableError(RetryLaterError):
    """A service that the call needs is down or slow (`unavailable`)."""


class ServerError(AlacartApiError):
    """The API failed (`server_error`). The app may retry later.

    A call that changes something may have gone through anyway. Read the data again before you
    repeat it.
    """
