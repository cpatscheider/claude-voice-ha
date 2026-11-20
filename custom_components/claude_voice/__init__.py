"""Claude Voice: a conversation agent backed by the claude-voice sidecar."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import SidecarClient, SidecarError
from .const import CONF_TOKEN, CONF_URL

PLATFORMS = [Platform.CONVERSATION]

type ClaudeVoiceConfigEntry = ConfigEntry[SidecarClient]


async def async_setup_entry(hass: HomeAssistant, entry: ClaudeVoiceConfigEntry) -> bool:
    client = SidecarClient(
        async_get_clientsession(hass), entry.data[CONF_URL], entry.data[CONF_TOKEN]
    )
    # Fail setup only if the sidecar is not there at all. A degraded sidecar still answers, and a
    # down CLI is what the fallback agent is for.
    try:
        await client.health()
    except SidecarError as err:
        raise ConfigEntryNotReady(f"sidecar not reachable: {err}") from err

    entry.runtime_data = client
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ClaudeVoiceConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: ClaudeVoiceConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
