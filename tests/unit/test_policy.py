import dataclasses
import json
from datetime import UTC, date, datetime, time
from decimal import Decimal
from enum import Enum, IntEnum
from pathlib import PurePosixPath
from typing import cast
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel

from langgraph_xai import PolicyAction
from langgraph_xai.core import ExecutionStartedEvent, ExplanationContext
from langgraph_xai.policy import (
    REDACTED,
    DefaultCapturePolicy,
    DefaultPolicyProvider,
    is_sensitive_key,
    sanitize_mapping,
    sanitize_value,
)
from tests.helpers import context, execution


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "Password",
        "api_key",
        "apiKey",
        "APIKey",
        "x-api-key",
        "OPENAI_API_KEY",
        "Authorization",
        "headers.authorization",
        "Set-Cookie",
        "cookie",
        "access_token",
        "accessToken",
        "refresh_token",
        "id_token",
        "clientSecret",
        "client secret",
        "db_password",
        "private_key",
        "secret",
        "database_dsn",
        "connection_string",
        "credentials",
        "auth",
        "basic_auth",
        "proxyAuth",
        "jwt",
        "session_jwt",
    ],
)
def test_credential_keys_are_sensitive(key: str) -> None:
    assert is_sensitive_key(key)


@pytest.mark.parametrize(
    "key",
    [
        "token_usage",
        "max_tokens",
        "input_tokens",
        "messages",
        "tool_calls",
        "keyword",
        "passage",
        "secretary",
        "author",
        "oauth_provider",
        "auth_method",
        "authored_by",
        "risk_score",
        "usage_metadata",
    ],
)
def test_ordinary_keys_are_not_sensitive(key: str) -> None:
    assert not is_sensitive_key(key)


class Color(Enum):
    RED = "red"


class Level(IntEnum):
    HIGH = 3


class Credentials(BaseModel):
    user: str
    api_key: str


class Unserializable(BaseModel):
    def model_dump(self, **kwargs: object) -> dict:
        raise RuntimeError("cannot dump")


@dataclasses.dataclass
class Point:
    x: int
    password: str


def test_values_are_converted_to_json_safe_data() -> None:
    moment = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    identifier = UUID(int=1)
    captured = sanitize_value(
        {
            "enum": Color.RED,
            "int_enum": Level.HIGH,
            "nan": float("nan"),
            "inf": float("inf"),
            "finite": 1.5,
            "datetime": moment,
            "date": date(2026, 1, 2),
            "time": time(3, 4),
            "uuid": identifier,
            "decimal": Decimal("1.10"),
            "path": PurePosixPath("/tmp/report.txt"),
            "bytes": b"\x00\x01\x02",
            "set": {"b", "a"},
            "tuple": (1, "two"),
            "model": Credentials(user="ana", api_key="sk-live"),
            "dataclass": Point(x=1, password="hunter2"),
            "class": Point,
            "object": object.__new__(Unserializable),
        }
    )

    assert isinstance(captured, dict)
    assert captured["enum"] == "red"
    assert captured["int_enum"] == 3
    assert captured["nan"] == "nan"
    assert captured["inf"] == "inf"
    assert captured["finite"] == 1.5
    assert captured["datetime"] == moment.isoformat()
    assert captured["date"] == "2026-01-02"
    assert captured["time"] == "03:04:00"
    assert captured["uuid"] == str(identifier)
    assert captured["decimal"] == "1.10"
    assert captured["path"] == "/tmp/report.txt"
    assert captured["bytes"] == "<3 bytes>"
    assert captured["set"] == ["a", "b"]
    assert captured["tuple"] == [1, "two"]
    assert captured["model"] == {"user": "ana", "api_key": REDACTED}
    assert captured["dataclass"] == {"x": 1, "password": REDACTED}
    assert "Point" in str(captured["class"])
    assert "Unserializable" in str(captured["object"])
    json.dumps(captured)


def test_cycles_and_deep_nesting_are_bounded() -> None:
    cyclic: dict[str, object] = {"name": "root"}
    cyclic["self"] = cyclic
    deep: list[object] = []
    cursor = deep
    for _ in range(50):
        child: list[object] = []
        cursor.append(child)
        cursor = child

    assert sanitize_value(cyclic) == {"name": "root", "self": "[circular reference]"}
    assert "[max depth exceeded]" in json.dumps(sanitize_value(deep))


def test_shared_references_are_not_mistaken_for_cycles() -> None:
    shared = {"value": 1}

    assert sanitize_value([shared, shared]) == [{"value": 1}, {"value": 1}]


def test_mapping_keys_become_strings_and_credentials_are_withheld() -> None:
    assert sanitize_mapping({1: "one", "nested": {"token": "abc", "safe": True}}) == {
        "1": "one",
        "nested": {"token": REDACTED, "safe": True},
    }


json_like = st.recursive(
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats()
    | st.text(max_size=10)
    | st.binary(max_size=8)
    | st.datetimes(timezones=st.just(UTC))
    | st.uuids()
    | st.decimals(allow_nan=False),
    lambda children: (
        st.lists(children, max_size=4)
        | st.tuples(children, children)
        | st.frozensets(st.text(max_size=5), max_size=3)
        | st.dictionaries(st.text(max_size=12), children, max_size=4)
    ),
    max_leaves=20,
)


@given(json_like)
def test_sanitized_values_are_always_strict_json(value: object) -> None:
    json.dumps(sanitize_value(value), allow_nan=False)


@given(json_like)
def test_sanitizing_is_idempotent(value: object) -> None:
    once = sanitize_value(value)

    assert sanitize_value(once) == once


secret_names = st.sampled_from(["password", "api_key", "Authorization", "accessToken", "x-api-key"])


@given(
    path=st.lists(st.text(alphabet="abcdefgh", min_size=1, max_size=6), max_size=4),
    name=secret_names,
    secret=st.text(alphabet="0123456789ABCDEF", min_size=12, max_size=20),
)
def test_credentials_never_survive_at_any_depth(path: list[str], name: str, secret: str) -> None:
    value: object = {name: secret}
    for key in reversed(path):
        value = cast("object", {key: [value]})

    assert secret not in json.dumps(sanitize_value(value))


async def test_default_capture_policy_allows_events() -> None:
    event = ExecutionStartedEvent(context=context(), sequence=0)

    decision = await DefaultCapturePolicy().evaluate(event)

    assert decision.allowed
    assert decision.action is PolicyAction.CAPTURE
    assert decision.context == event.context


async def test_default_exposure_policy_withholds_raw_and_private_fields() -> None:
    explanation_context = ExplanationContext(execution=execution(), audience="end_user")

    exposure = await DefaultPolicyProvider().evaluate(explanation_context, PolicyAction.EXPOSE)
    capture = await DefaultPolicyProvider().evaluate(explanation_context, PolicyAction.CAPTURE)

    assert exposure.allowed
    assert exposure.audience == "end_user"
    assert exposure.denied_fields == {"private_memory", "raw_content", "content_reference"}
    assert capture.allowed
    assert capture.denied_fields == set()
    assert capture.reason == "Allowed; only exposure is restricted by default."


credential_names = st.sampled_from(
    [
        "password",
        "api_key",
        "access_token",
        "client_secret",
        "private_key",
        "authorization",
        "token",
        "secret",
        "cookie",
        "dsn",
        "jwt",
        "credentials",
    ]
)
lowercase = "abcdefghijklmnopqrstuvwxyz"


def camel_case(key: str) -> str:
    head, *rest = key.split("_")
    return head + "".join(part.capitalize() for part in rest)


@given(
    name=credential_names,
    prefix=st.text(alphabet=lowercase + "0123456789", max_size=6),
    path=st.lists(st.sampled_from(["headers", "env", "config"]), max_size=2),
)
def test_credential_names_match_in_every_spelling(name: str, prefix: str, path: list[str]) -> None:
    key = f"{prefix}_{name}" if prefix else name
    spellings = (key, key.upper(), key.replace("_", "-"), key.replace("_", " "), camel_case(key))

    for spelling in spellings:
        assert is_sensitive_key(".".join([*path, spelling]))


@given(st.text(alphabet=lowercase + "_- ", max_size=24))
def test_case_and_separators_never_change_the_verdict(key: str) -> None:
    verdict = is_sensitive_key(key)

    assert is_sensitive_key(key.upper()) is verdict
    assert is_sensitive_key(key.replace("-", "_")) is verdict
    assert is_sensitive_key(key.replace(" ", "-")) is verdict


segments = st.text(alphabet=lowercase + "ABCDEFGHIJ0123456789_- ", max_size=16)


@given(first=segments, second=segments)
def test_dotted_keys_are_sensitive_when_any_segment_is(first: str, second: str) -> None:
    assert is_sensitive_key(f"{first}.{second}") is (
        is_sensitive_key(first) or is_sensitive_key(second)
    )
