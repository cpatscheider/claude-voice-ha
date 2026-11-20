import aiohttp
import pytest

from custom_components.claude_voice import client as client_mod
from custom_components.claude_voice.client import (
    AuthError,
    Delta,
    Done,
    SidecarClient,
    SidecarError,
    ToolUse,
)

from .conftest import TOKEN


async def _collect(client, body=None):
    return [e async for e in client.turn(body or {"conversation_id": "c", "text": "hi"})]


async def test_streams_deltas_tools_and_done(sidecar):
    sidecar.script = [
        ("delta", {"text": "Im Bad "}),
        ("tool", {"name": "mcp__homeassistant__GetLiveContext"}),
        ("delta", {"text": "sind es 18 Grad."}),
        ("done", {"text": "Im Bad sind es 18 Grad.", "latency_ms": {"total_ms": 7}}),
    ]
    async with aiohttp.ClientSession() as s:
        events = await _collect(SidecarClient(s, sidecar.url, TOKEN))
    assert events == [
        Delta("Im Bad "),
        ToolUse("mcp__homeassistant__GetLiveContext"),
        Delta("sind es 18 Grad."),
        Done("Im Bad sind es 18 Grad.", {"total_ms": 7}, None),
    ]
    assert sidecar.turns[0]["conversation_id"] == "c"


@pytest.mark.parametrize("code", ["timeout", "cli_down", "auth_expired", "rate_limited", "busy"])
async def test_error_event_raises_with_contract_code(sidecar, code):
    sidecar.fail(code)
    async with aiohttp.ClientSession() as s:
        with pytest.raises(SidecarError) as exc:
            await _collect(SidecarClient(s, sidecar.url, TOKEN))
    assert exc.value.code == code


async def test_stream_without_done_is_an_error(sidecar):
    sidecar.script = [("delta", {"text": "Halb"})]
    async with aiohttp.ClientSession() as s:
        with pytest.raises(SidecarError) as exc:
            await _collect(SidecarClient(s, sidecar.url, TOKEN))
    assert exc.value.code == "protocol"


async def test_wrong_token(sidecar):
    async with aiohttp.ClientSession() as s:
        c = SidecarClient(s, sidecar.url, "nope")
        with pytest.raises(AuthError):
            await _collect(c)
        with pytest.raises(AuthError):
            await c.reset("x")


async def test_unreachable(socket_enabled):
    async with aiohttp.ClientSession() as s:
        c = SidecarClient(s, "http://127.0.0.1:9", TOKEN)
        with pytest.raises(SidecarError) as exc:
            await c.health()
        assert exc.value.code == "unreachable"
        with pytest.raises(SidecarError) as exc:
            await _collect(c)
        assert exc.value.code == "unreachable"


async def test_silent_sidecar_times_out(sidecar, monkeypatch):
    monkeypatch.setattr(client_mod, "READ_TIMEOUT", 0.3)
    sidecar.script = [("delta", {"text": "Moment"})]
    sidecar.hang = True
    async with aiohttp.ClientSession() as s:
        with pytest.raises(SidecarError) as exc:
            await _collect(SidecarClient(s, sidecar.url, TOKEN))
    assert exc.value.code == "timeout"


async def test_health_and_reset(sidecar):
    async with aiohttp.ClientSession() as s:
        c = SidecarClient(s, sidecar.url + "/", TOKEN)
        assert (await c.health())["status"] == "ok"
        await c.reset("abc")
    assert sidecar.resets == ["abc"]
