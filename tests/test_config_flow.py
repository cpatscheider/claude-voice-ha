from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.claude_voice.const import (
    CONF_AREA_FIRST,
    CONF_DOMAINS,
    CONF_FALLBACK_AGENT,
    CONF_MAX_ENTITIES,
    CONF_SENSOR_CLASSES,
    CONF_TOKEN,
    CONF_URL,
    DOMAIN,
)

from .conftest import TOKEN


async def _start(hass):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def test_user_flow_creates_entry(hass, sidecar):
    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: sidecar.url + "/", CONF_TOKEN: TOKEN}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_URL: sidecar.url, CONF_TOKEN: TOKEN}
    assert sidecar.resets == ["config-flow-probe"]


async def test_user_flow_bad_token(hass, sidecar):
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: sidecar.url, CONF_TOKEN: "wrong"}
    )
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_unreachable(hass, socket_enabled):
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: "http://127.0.0.1:9", CONF_TOKEN: TOKEN}
    )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_options_flow(hass, sidecar):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_URL: sidecar.url, CONF_TOKEN: TOKEN})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    opts = {
        CONF_DOMAINS: ["light", "weather"],
        CONF_SENSOR_CLASSES: ["temperature"],
        CONF_MAX_ENTITIES: 50,
        CONF_AREA_FIRST: False,
        CONF_FALLBACK_AGENT: "conversation.home_assistant",
    }
    result = await hass.config_entries.options.async_configure(result["flow_id"], opts)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == opts
