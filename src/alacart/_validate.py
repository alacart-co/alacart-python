"""Checks of the arguments that callers pass, made before any request goes out."""

from __future__ import annotations

from collections.abc import Iterable


def check_id(name: str, value: str) -> str:
    """Return `value` if it can be an id, and raise otherwise.

    Ids are opaque strings that the API returned. A segment of "." or ".." would move a path to
    another endpoint, because an HTTP client resolves it even when it is percent-encoded.
    """
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string id, got {type(value).__name__}")
    if value in ("", ".", ".."):
        raise ValueError(f"{name} is not an id: {value!r}")
    return value


def check_optional_id(name: str, value: str | None) -> str | None:
    return None if value is None else check_id(name, value)


def check_ids(name: str, values: Iterable[str]) -> list[str]:
    return [check_id(name, value) for value in check_strings(name, values)]


def check_strings(name: str, values: Iterable[str]) -> list[str]:
    """Return `values` as a list, and refuse a single string.

    A string is itself an iterable of strings, so one text where a list belongs would otherwise
    become one entry per character.
    """
    if isinstance(values, str):
        raise TypeError(f"{name} must be a list of strings, not a single string")
    return list(values)
