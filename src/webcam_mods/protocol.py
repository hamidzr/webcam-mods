"""Bounded, strict JSONL requests for the local control pipe."""

from dataclasses import dataclass
import json
import math
from typing import Any, Iterator, TextIO

MAX_REQUEST_BYTES = 64 * 1024
RequestID = int | str


@dataclass(frozen=True)
class Request:
    id: RequestID
    method: str
    params: dict[str, Any]


@dataclass(frozen=True)
class RequestFailure:
    id: RequestID | None
    error: str


def _constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON number: {value}")


def _float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("JSON number is out of range")
    return result


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


def _valid_id(value: object) -> bool:
    return (
        type(value) is int
        and abs(value) <= 2**53 - 1
        or isinstance(value, str)
        and 1 <= len(value) <= 128
        and all(ord(char) >= 32 for char in value)
    )


def parse_request(line: str) -> Request | RequestFailure:
    identifier: RequestID | None = None
    try:
        if len(line.encode("utf-8")) > MAX_REQUEST_BYTES:
            raise ValueError("request exceeds 64 KiB limit")
        data = json.loads(
            line,
            parse_constant=_constant,
            parse_float=_float,
            object_pairs_hook=_object,
        )
        if not isinstance(data, dict) or not _valid_id(data.get("id")):
            raise ValueError("request requires an integer or nonempty string id")
        identifier = data["id"]
        method = data.get("method")
        if not isinstance(method, str) or not 1 <= len(method) <= 64:
            raise ValueError("method must be a string of 1..64 characters")
        params = data.get("params", {})
        if not isinstance(params, dict):
            raise ValueError("params must be an object")
        return Request(identifier, method, params)
    except ValueError, UnicodeError, RecursionError:
        # do not echo malformed payloads or decoder fragments into logs/UI
        return RequestFailure(
            identifier, "invalid request: bounded strict JSON object required"
        )


def read_requests(stream: TextIO) -> Iterator[Request | RequestFailure]:
    """Drain oversized records in bounded chunks, then resume at the next line."""
    while True:
        line = stream.readline(MAX_REQUEST_BYTES + 1)
        if not line:
            return
        if len(line) > MAX_REQUEST_BYTES:
            while not line.endswith("\n"):
                line = stream.readline(MAX_REQUEST_BYTES + 1)
                if not line:
                    break
            yield RequestFailure(None, "request exceeds 64 KiB limit")
        else:
            yield parse_request(line)
