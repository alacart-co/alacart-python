"""Helpers that read the API's JSON.

Each helper raises `AlacartResponseError` when a value does not have the type the API documents.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from .exceptions import AlacartResponseError


def as_mapping(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AlacartResponseError(f"Expected a JSON object, got {type(value).__name__}")
    return value


def as_str(value: Any) -> str:
    if not isinstance(value, str):
        raise AlacartResponseError(f"Expected a string, got {type(value).__name__}")
    return value


def require(data: Mapping[str, Any], key: str) -> Any:
    try:
        return data[key]
    except KeyError:
        raise AlacartResponseError(f"The answer has no field {key}") from None


def get_str(data: Mapping[str, Any], key: str) -> str:
    value = require(data, key)
    if not isinstance(value, str):
        raise _wrong_type(key, "a string", value)
    return value


def get_opt_str(data: Mapping[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is not None and not isinstance(value, str):
        raise _wrong_type(key, "a string or null", value)
    return value


def get_bool(data: Mapping[str, Any], key: str) -> bool:
    value = require(data, key)
    if not isinstance(value, bool):
        raise _wrong_type(key, "a boolean", value)
    return value


def get_int(data: Mapping[str, Any], key: str) -> int:
    value = require(data, key)
    if not _is_int(value):
        raise _wrong_type(key, "an integer", value)
    return int(value)


def get_opt_int(data: Mapping[str, Any], key: str) -> int | None:
    value = data.get(key)
    if value is None:
        return None
    if not _is_int(value):
        raise _wrong_type(key, "an integer or null", value)
    return int(value)


def get_opt_float(data: Mapping[str, Any], key: str) -> float | None:
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _wrong_type(key, "a number or null", value)
    return float(value)


def get_time(data: Mapping[str, Any], key: str) -> datetime:
    return _parse_time(key, require(data, key))


def get_opt_time(data: Mapping[str, Any], key: str) -> datetime | None:
    value = data.get(key)
    return None if value is None else _parse_time(key, value)


def get_list[T](data: Mapping[str, Any], key: str, parse: Callable[[Any], T]) -> list[T]:
    value = require(data, key)
    if not isinstance(value, list):
        raise _wrong_type(key, "an array", value)
    return [parse(entry) for entry in value]


def get_objects[T](
    data: Mapping[str, Any], key: str, parse: Callable[[Mapping[str, Any]], T]
) -> list[T]:
    """Read an array of JSON objects, and parse each one with `parse`."""
    return get_list(data, key, lambda entry: parse(as_mapping(entry)))


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _parse_time(key: str, value: Any) -> datetime:
    if not isinstance(value, str):
        raise _wrong_type(key, "a timestamp", value)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise AlacartResponseError(f"Field {key} is not a timestamp: {value!r}") from None
    # The API sends every timestamp in UTC with its offset. A time without an offset could not be
    # compared with the times the API sends.
    if parsed.tzinfo is None:
        raise AlacartResponseError(f"Field {key} has no time zone: {value!r}")
    return parsed


def _wrong_type(key: str, expected: str, value: Any) -> AlacartResponseError:
    return AlacartResponseError(f"Field {key} should be {expected}, got {type(value).__name__}")
