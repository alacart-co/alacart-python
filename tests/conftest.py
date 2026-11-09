"""Shared fixtures for the tests.

The tests run the client against `FakeApi`, a small aiohttp server that answers each request with
a canned answer and records what the client sent. It also checks each request against the API's
OpenAPI document. It checks that the method and path match one documented operation, that every
query parameter is documented and every required one is there, and that the body fits the
documented schema with no undocumented fields. It does not check query values or path
parameters, because the document gives them no rules beyond their type.
"""

from __future__ import annotations

import asyncio
import copy
import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from jsonschema import Draft202012Validator
from multidict import CIMultiDictProxy, MultiMapping
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from alacart import AlacartClient, StaticTokenAuth

FIXTURES = Path(__file__).parent / "fixtures"
TOKEN = "test-access-token"

OPENAPI: dict[str, Any] = json.loads(
    (Path(__file__).parent / "openapi.v1.json").read_text(encoding="utf-8")
)
"""The API's OpenAPI document, as beta serves it at `/openapi/v1.json`."""


def openapi_registry(document: dict[str, Any]) -> Registry[Any]:
    """Return a registry that resolves `urn:openapi#/...` references into `document`."""
    resource: Resource[Any] = Resource.from_contents(document, default_specification=DRAFT202012)
    registry: Registry[Any] = Registry().with_resource("urn:openapi", resource)
    return registry


def schema_ref(*parts: str) -> dict[str, str]:
    """Return a schema that refers to the OpenAPI document at the path `parts`."""
    escaped = (part.replace("~", "~0").replace("/", "~1") for part in parts)
    return {"$ref": "urn:openapi#/" + "/".join(escaped)}


def _strict(document: dict[str, Any]) -> dict[str, Any]:
    # The document allows fields it does not name, so that the API can add fields. A request
    # that the client sends must use only the fields the document names.
    strict = copy.deepcopy(document)

    def forbid_extra_fields(node: Any) -> None:
        if isinstance(node, dict):
            if "properties" in node:
                node["additionalProperties"] = False
            for value in node.values():
                forbid_extra_fields(value)
        elif isinstance(node, list):
            for value in node:
                forbid_extra_fields(value)

    forbid_extra_fields(strict)
    return strict


_REQUEST_REGISTRY = openapi_registry(_strict(OPENAPI))
_OPERATIONS = [
    (re.compile("^" + re.sub(r"\\{[^}]+\\}", "[^/]+", re.escape(path)) + "$"), path, method)
    for path, path_item in OPENAPI["paths"].items()
    for method in path_item
]


def request_violations(
    method: str, raw_path: str, query: MultiMapping[str], body: Any
) -> list[str]:
    """Return how a request breaks the OpenAPI document, or an empty list if it does not."""
    matches = [
        (path, operation_method)
        for pattern, path, operation_method in _OPERATIONS
        if operation_method == method.lower() and pattern.match(raw_path)
    ]
    if len(matches) != 1:
        return [f"{method} {raw_path} matches {len(matches)} documented operations"]
    path, operation_method = matches[0]
    operation = OPENAPI["paths"][path][operation_method]
    violations: list[str] = []

    query_parameters = [p for p in operation.get("parameters", []) if p["in"] == "query"]
    declared = {p["name"] for p in query_parameters}
    violations.extend(
        f"{method} {path} sends the undocumented query parameter {key}"
        for key in query
        if key not in declared
    )
    violations.extend(
        f"{method} {path} leaves out the required query parameter {p['name']}"
        for p in query_parameters
        if p.get("required") and p["name"] not in query
    )

    request_body = operation.get("requestBody")
    if request_body is None:
        if body is not None:
            violations.append(f"{method} {path} sends a body that the document does not take")
    else:
        validator = Draft202012Validator(
            schema_ref(
                "paths",
                path,
                operation_method,
                "requestBody",
                "content",
                "application/json",
                "schema",
            ),
            registry=_REQUEST_REGISTRY,
        )
        violations.extend(
            f"{method} {path} body: {error.message}" for error in validator.iter_errors(body)
        )
    return violations


def load_fixture(name: str) -> Any:
    """Return the JSON of `tests/fixtures/<name>.json`."""
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@dataclass(frozen=True)
class SentRequest:
    """A request that the fake API received."""

    method: str
    path: str
    """The path as sent, with its percent-encoding and without the query."""
    query: MultiMapping[str]
    headers: CIMultiDictProxy[str]
    json: Any


@dataclass(frozen=True)
class _CannedAnswer:
    status: int
    body: bytes
    headers: dict[str, str]
    delay: float
    body_delay: float


@dataclass
class FakeApi:
    """Answers requests with canned answers, in the order the test adds them."""

    base_url: str = ""
    """The server's address, which the test's client calls."""
    requests: list[SentRequest] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    """How the requests broke the OpenAPI document. The `api` fixture fails the test on any."""
    _answers: dict[tuple[str, str], list[_CannedAnswer]] = field(default_factory=dict)

    def answer(
        self,
        method: str,
        path: str,
        *,
        status: int = 200,
        json_body: Any = None,
        body: str | None = None,
        content_type: str = "application/json",
        headers: dict[str, str] | None = None,
        delay: float = 0,
        body_delay: float = 0,
    ) -> None:
        """Answer the next `method` request to `path` this way.

        `path` is percent-encoded as the client sends it, without the query. `delay` waits before
        the answer starts, and `body_delay` waits after the first byte of the body.
        """
        if json_body is not None:
            body = json.dumps(json_body)
        all_headers = dict(headers or {})
        if body is not None:
            all_headers.setdefault("Content-Type", content_type)
        self._answers.setdefault((method, path), []).append(
            _CannedAnswer(status, (body or "").encode(), all_headers, delay, body_delay)
        )

    def problem(self, method: str, path: str, fixture: str, **kwargs: Any) -> None:
        """Answer with the problem response in a fixture, using the status it names."""
        problem = load_fixture(fixture)
        self.answer(
            method,
            path,
            status=problem["status"],
            json_body=problem,
            content_type="application/problem+json",
            **kwargs,
        )

    def sent(self, method: str, path: str) -> SentRequest:
        """Return the one request sent with `method` to `path`."""
        matches = [r for r in self.requests if (r.method, r.path) == (method, path)]
        assert len(matches) == 1, f"{len(matches)} requests to {method} {path}"
        return matches[0]

    async def handle(self, request: web.Request) -> web.StreamResponse:
        path = request.rel_url.raw_path
        body = await request.read()
        sent = SentRequest(
            method=request.method,
            path=path,
            query=request.query,
            headers=request.headers,
            json=json.loads(body) if body else None,
        )
        self.requests.append(sent)
        self.violations.extend(request_violations(sent.method, path, sent.query, sent.json))
        answers = self._answers.get((request.method, path))
        if not answers:
            # 418 maps to no particular exception, so no test can pass on this answer by luck.
            self.violations.append(f"The test gave no answer for {request.method} {path}")
            return web.Response(status=418, text=f"No answer for {request.method} {path}")
        answer = answers.pop(0)
        if answer.delay:
            await asyncio.sleep(answer.delay)
        if not answer.body_delay:
            return web.Response(status=answer.status, body=answer.body, headers=answer.headers)
        response = web.StreamResponse(status=answer.status, headers=answer.headers)
        response.content_length = len(answer.body)
        await response.prepare(request)
        await response.write(answer.body[:1])
        await asyncio.sleep(answer.body_delay)
        await response.write(answer.body[1:])
        return response


@pytest.fixture
async def api() -> AsyncIterator[FakeApi]:
    fake = FakeApi()
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", fake.handle)
    server = TestServer(app)
    await server.start_server()
    fake.base_url = str(server.make_url("")).rstrip("/")
    try:
        yield fake
    finally:
        await server.close()
    assert fake.violations == []


@pytest.fixture
async def session() -> AsyncIterator[aiohttp.ClientSession]:
    async with aiohttp.ClientSession() as client_session:
        yield client_session


@pytest.fixture
def client(api: FakeApi, session: aiohttp.ClientSession) -> AlacartClient:
    return AlacartClient(StaticTokenAuth(session, api.base_url, TOKEN))
