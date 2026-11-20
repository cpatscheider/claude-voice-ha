"""Fixtures: a fake sidecar that speaks the interface contract over real HTTP."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

TOKEN = "test-token"


@dataclass
class FakeSidecar:
    """Scripted sidecar. `script` is a list of (event, data) pairs sent for every turn."""

    script: list[tuple[str, dict]] = field(default_factory=list)
    health: dict[str, Any] = field(
        default_factory=lambda: {"status": "ok", "cli": "warm", "auth": "ok", "cli_version": "x"}
    )
    turns: list[dict] = field(default_factory=list)
    resets: list[str] = field(default_factory=list)
    hang: bool = False
    server: TestServer | None = None

    @property
    def url(self) -> str:
        assert self.server is not None
        return str(self.server.make_url("")).rstrip("/")

    def answer(self, *chunks: str) -> None:
        self.script = [("delta", {"text": c}) for c in chunks] + [
            ("done", {"text": "".join(chunks), "latency_ms": {"first_delta_ms": 5, "total_ms": 9}})
        ]

    def fail(self, code: str) -> None:
        self.script = [("error", {"code": code, "message": "scripted"})]

    def _authorised(self, request: web.Request) -> bool:
        return request.headers.get("Authorization") == f"Bearer {TOKEN}"

    async def _health(self, request: web.Request) -> web.Response:
        return web.json_response(self.health)

    async def _reset(self, request: web.Request) -> web.Response:
        if not self._authorised(request):
            return web.Response(status=401, text="bad token")
        self.resets.append((await request.json())["conversation_id"])
        return web.Response(status=204)

    async def _turn(self, request: web.Request) -> web.StreamResponse:
        if not self._authorised(request):
            return web.Response(status=401, text="bad token")
        self.turns.append(await request.json())
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await resp.prepare(request)
        for event, data in self.script:
            await resp.write(f"event: {event}\ndata: {json.dumps(data)}\n\n".encode())
        if self.hang:
            await asyncio.sleep(3600)
        await resp.write_eof()
        return resp

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/healthz", self._health)
        app.router.add_post("/v1/reset", self._reset)
        app.router.add_post("/v1/turn", self._turn)
        return app


@pytest.fixture
async def sidecar(socket_enabled) -> FakeSidecar:
    fake = FakeSidecar()
    fake.answer("Erledigt, ", "das Licht ist an.")
    fake.server = TestServer(fake.app(), host="127.0.0.1")
    await fake.server.start_server()
    yield fake
    await fake.server.close()


@pytest.fixture(autouse=True)
async def ha_core(hass, enable_custom_integrations):
    """Real HA always runs the `homeassistant` component, which owns Assist exposure."""
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, "homeassistant", {})
    yield
