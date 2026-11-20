"""HTTP/SSE client for the claude-voice sidecar.

Deliberately free of Home Assistant imports so it can be tested against a fake sidecar on its own.
The wire format is the interface contract in the build plan.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from .const import CONNECT_TIMEOUT, READ_TIMEOUT


class SidecarError(Exception):
    """A turn failed. `code` is a contract error code, or `unreachable` / `protocol`."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code
        self.message = message


class AuthError(SidecarError):
    """The sidecar rejected the bearer token."""

    def __init__(self, message: str = "") -> None:
        super().__init__("unauthorized", message)


@dataclass
class Delta:
    text: str


@dataclass
class ToolUse:
    name: str


@dataclass
class Done:
    text: str
    latency_ms: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, Any] | None = None


Event = Delta | ToolUse | Done


async def _iter_sse(resp: aiohttp.ClientResponse) -> AsyncIterator[tuple[str, str]]:
    """Yield (event, data) pairs. Handles multi-line data and blank-line dispatch."""
    event = "message"
    data: list[str] = []
    async for raw in resp.content:
        line = raw.decode("utf-8").rstrip("\r\n")
        if not line:
            if data:
                yield event, "\n".join(data)
            event, data = "message", []
        elif line.startswith(":"):
            continue
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip(" "))
    if data:
        yield event, "\n".join(data)


class SidecarClient:
    """Talks to one sidecar. The aiohttp session is owned by Home Assistant."""

    def __init__(self, session: aiohttp.ClientSession, url: str, token: str) -> None:
        self._session = session
        self._url = url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}

    async def health(self) -> dict[str, Any]:
        try:
            async with self._session.get(
                f"{self._url}/healthz",
                timeout=aiohttp.ClientTimeout(total=CONNECT_TIMEOUT),
            ) as resp:
                resp.raise_for_status()
                return await resp.json()
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise SidecarError("unreachable", str(err)) from err

    async def reset(self, conversation_id: str) -> None:
        """Drop a session. Also the cheapest call that proves the token is right."""
        try:
            async with self._session.post(
                f"{self._url}/v1/reset",
                json={"conversation_id": conversation_id},
                headers=self._headers,
                timeout=aiohttp.ClientTimeout(total=CONNECT_TIMEOUT),
            ) as resp:
                if resp.status == 401:
                    raise AuthError(await resp.text())
                resp.raise_for_status()
        except AuthError:
            raise
        except (aiohttp.ClientError, TimeoutError) as err:
            raise SidecarError("unreachable", str(err)) from err

    async def turn(self, body: dict[str, Any]) -> AsyncIterator[Event]:
        """Run one turn. Yields events; raises SidecarError on an `error` event or I/O failure.

        A stream that ends without `done` is an error too: the sidecar always closes with one of
        `done` or `error`, so anything else means it died mid-turn.
        """
        timeout = aiohttp.ClientTimeout(
            total=None, connect=CONNECT_TIMEOUT, sock_read=READ_TIMEOUT
        )
        try:
            async with self._session.post(
                f"{self._url}/v1/turn",
                json=body,
                headers={**self._headers, "Accept": "text/event-stream"},
                timeout=timeout,
            ) as resp:
                if resp.status == 401:
                    raise AuthError(await resp.text())
                if resp.status != 200:
                    raise SidecarError("protocol", f"HTTP {resp.status}")
                async for event, raw in _iter_sse(resp):
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError as err:
                        raise SidecarError("protocol", f"bad JSON in {event}") from err
                    if event == "delta":
                        if text := data.get("text"):
                            yield Delta(text)
                    elif event == "tool":
                        yield ToolUse(data.get("name", "unknown"))
                    elif event == "done":
                        yield Done(
                            text=data.get("text") or "",
                            latency_ms=data.get("latency_ms") or {},
                            usage=data.get("usage"),
                        )
                        return
                    elif event == "error":
                        raise SidecarError(
                            data.get("code", "unknown"), data.get("message", "")
                        )
        except SidecarError:
            raise
        except TimeoutError as err:
            raise SidecarError("timeout", "sidecar stopped responding") from err
        except aiohttp.ClientError as err:
            raise SidecarError("unreachable", str(err)) from err
        raise SidecarError("protocol", "stream ended without done")
