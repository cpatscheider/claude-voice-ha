"""End-to-end against a real Home Assistant core and the fake sidecar over HTTP."""

from __future__ import annotations

import pytest
from homeassistant.components import conversation
from homeassistant.components.homeassistant.exposed_entities import async_expose_entity
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er
from homeassistant.helpers.chat_session import async_get_chat_session
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.claude_voice.const import (
    CONF_FALLBACK_AGENT,
    CONF_TOKEN,
    CONF_URL,
    DOMAIN,
    UNREACHABLE_MESSAGE,
)

from .conftest import TOKEN

AGENT = "conversation.claude_voice"


async def _setup(hass: HomeAssistant, sidecar, options=None) -> MockConfigEntry:
    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(hass, "conversation", {})
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_URL: sidecar.url, CONF_TOKEN: TOKEN}, options=options or {}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _ask(hass, text, conversation_id=None, **kw):
    return await conversation.async_converse(
        hass, text, conversation_id, Context(), language="de", agent_id=AGENT, **kw
    )


def _speech(result) -> str:
    return result.response.speech["plain"]["speech"]


async def test_agent_registers_and_answers(hass, sidecar):
    await _setup(hass, sidecar)
    assert hass.states.get(AGENT) is not None

    result = await _ask(hass, "Mach das Licht an")

    assert _speech(result) == "Erledigt, das Licht ist an."
    body = sidecar.turns[0]
    assert body["text"] == "Mach das Licht an"
    assert body["language"] == "de"
    assert body["conversation_id"] == result.conversation_id
    assert body["context"]["area"] is None
    assert body["context"]["now"]
    attrs = hass.states.get(AGENT).attributes
    assert attrs["last_error"] is None and attrs["last_total_ms"] == 9


async def test_follow_up_reuses_the_conversation_id(hass, sidecar):
    await _setup(hass, sidecar)
    first = await _ask(hass, "Eins")
    await _ask(hass, "Zwei", conversation_id=first.conversation_id)
    assert sidecar.turns[1]["conversation_id"] == first.conversation_id


async def test_deltas_reach_the_pipeline_listener(hass, sidecar):
    """What the Assist pipeline does: attach a delta listener, then converse in that session."""
    await _setup(hass, sidecar)
    seen: list[dict] = []
    with (
        async_get_chat_session(hass) as session,
        conversation.async_get_chat_log(
            hass, session, None, chat_log_delta_listener=lambda _log, d: seen.append(d)
        ),
    ):
        result = await _ask(hass, "Licht an", conversation_id=session.conversation_id)
    assert [d["content"] for d in seen if d.get("content")] == ["Erledigt, ", "das Licht ist an."]
    assert _speech(result) == "Erledigt, das Licht ist an."


async def test_snapshot_only_exposed_entities_speaker_area_first(hass, sidecar):
    areas = ar.async_get(hass)
    wz = areas.async_create("Wohnzimmer")
    bad = areas.async_create("Bad")
    entry = await _setup(hass, sidecar)
    ents = er.async_get(hass)
    devs = dr.async_get(hass)

    def add(domain, oid, state, attrs=None, area=None, expose=True):
        e = ents.async_get_or_create(domain, "test", oid, suggested_object_id=oid)
        if area:
            ents.async_update_entity(e.entity_id, area_id=area.id)
        hass.states.async_set(e.entity_id, state, attrs or {})
        async_expose_entity(hass, "conversation", e.entity_id, expose)
        return e.entity_id

    add("light", "decke", "on", {"friendly_name": "Decke", "brightness": 255}, wz)
    add("light", "geheim", "on", {"friendly_name": "Geheim"}, wz, expose=False)
    add("sensor", "bad_temp", "18.24", {"friendly_name": "Temperatur Bad",
        "device_class": "temperature", "unit_of_measurement": "°C"}, bad)
    add("sensor", "bad_power", "12", {"friendly_name": "Leistung", "device_class": "power",
        "unit_of_measurement": "W"}, bad)
    add("sensor", "tado", "unavailable", {"friendly_name": "Tado", "device_class": "temperature"}, bad)
    add("weather", "home", "cloudy", {"friendly_name": "Forecast Home", "temperature": 4})

    sat = devs.async_get_or_create(config_entry_id=entry.entry_id, identifiers={("test", "sat")})
    devs.async_update_device(sat.id, area_id=wz.id)

    await _ask(hass, "Wie warm ist es?", device_id=sat.id)

    body = sidecar.turns[0]
    assert body["context"]["area"] == "Wohnzimmer"
    assert body["snapshot"] == (
        "## Wohnzimmer\nDecke|light|on|100%\n"
        "## Bad\nTemperatur Bad|sensor|18.2°C\n"
        "## Ohne Raum\nForecast Home|weather|cloudy|4°C"
    )


async def test_failure_without_fallback_says_unreachable(hass, sidecar):
    await _setup(hass, sidecar)
    sidecar.fail("cli_down")
    result = await _ask(hass, "Licht an")
    assert _speech(result) == UNREACHABLE_MESSAGE
    assert hass.states.get(AGENT).attributes["last_error"] == "cli_down"


@pytest.mark.parametrize("code", ["timeout", "rate_limited", "busy", "auth_expired"])
async def test_failure_hands_the_turn_to_the_fallback(hass, sidecar, code):
    await _setup(hass, sidecar, {CONF_FALLBACK_AGENT: "conversation.home_assistant"})
    sidecar.fail(code)
    seen: list[dict] = []
    with (
        async_get_chat_session(hass) as session,
        conversation.async_get_chat_log(
            hass, session, None, chat_log_delta_listener=lambda _log, d: seen.append(d)
        ) as chat_log,
    ):
        result = await _ask(hass, "Blubber", conversation_id=session.conversation_id)
    # The built-in agent cannot parse "Blubber", but it answered: the turn was handed over.
    assert _speech(result) not in ("", UNREACHABLE_MESSAGE)
    assert result.conversation_id == session.conversation_id
    assert chat_log.content[-1].agent_id == "conversation.home_assistant"
    assert hass.states.get(AGENT).attributes["last_fallback"] == "conversation.home_assistant"


async def test_sidecar_gone_uses_fallback(hass, sidecar):
    await _setup(hass, sidecar, {CONF_FALLBACK_AGENT: "conversation.home_assistant"})
    await sidecar.server.close()
    result = await _ask(hass, "Blubber")
    assert _speech(result) not in ("", UNREACHABLE_MESSAGE)
    assert hass.states.get(AGENT).attributes["last_error"] == "unreachable"


async def test_partial_answer_is_kept_not_duplicated_by_the_fallback(hass, sidecar):
    await _setup(hass, sidecar, {CONF_FALLBACK_AGENT: "conversation.home_assistant"})
    sidecar.script = [("delta", {"text": "Im Bad sind es "}), ("error", {"code": "timeout"})]
    result = await _ask(hass, "Wie warm ist es im Bad?")
    assert _speech(result) == "Im Bad sind es "
    assert hass.states.get(AGENT).attributes["last_fallback"] is None


async def test_done_without_deltas_still_speaks(hass, sidecar):
    await _setup(hass, sidecar)
    sidecar.script = [("done", {"text": "Ganz ohne Deltas."})]
    assert _speech(await _ask(hass, "x")) == "Ganz ohne Deltas."


async def test_setup_retries_when_sidecar_is_down(hass, sidecar):
    url = sidecar.url
    await sidecar.server.close()
    assert await async_setup_component(hass, "conversation", {})
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_URL: url, CONF_TOKEN: TOKEN})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state.name == "SETUP_RETRY"
