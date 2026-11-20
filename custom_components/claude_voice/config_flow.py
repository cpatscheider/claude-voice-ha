"""Config and options flow."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.helpers import entity_registry as er, selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import AuthError, SidecarClient, SidecarError
from .const import (
    CONF_AREA_FIRST,
    CONF_DOMAINS,
    CONF_FALLBACK_AGENT,
    CONF_MAX_ENTITIES,
    CONF_SENSOR_CLASSES,
    CONF_TOKEN,
    CONF_URL,
    DEFAULT_AREA_FIRST,
    DEFAULT_DOMAINS,
    DEFAULT_MAX_ENTITIES,
    DEFAULT_SENSOR_CLASSES,
    DEFAULT_URL,
    DOMAIN,
    SELECTABLE_DOMAINS,
)

SENSOR_CLASSES = [
    "temperature",
    "humidity",
    "power",
    "energy",
    "battery",
    "illuminance",
    "pm25",
    "aqi",
    "co2",
    "precipitation",
    "wind_speed",
]


async def _validate(hass, url: str, token: str) -> str | None:
    """Return an error key, or None if the sidecar answers and accepts the token."""
    client = SidecarClient(async_get_clientsession(hass), url, token)
    try:
        await client.health()
        # /healthz is unauthenticated, so prove the token on /v1/reset with a throwaway id.
        await client.reset("config-flow-probe")
    except AuthError:
        return "invalid_auth"
    except SidecarError:
        return "cannot_connect"
    return None


class ClaudeVoiceConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_URL].rstrip("/")
            await self.async_set_unique_id(url)
            self._abort_if_unique_id_configured()
            if not (error := await _validate(self.hass, url, user_input[CONF_TOKEN])):
                return self.async_create_entry(
                    title="Claude Voice", data={CONF_URL: url, CONF_TOKEN: user_input[CONF_TOKEN]}
                )
            errors["base"] = error

        schema = vol.Schema(
            {
                vol.Required(CONF_URL, default=DEFAULT_URL): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
                ),
                vol.Required(CONF_TOKEN): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_URL].rstrip("/")
            if not (error := await _validate(self.hass, url, user_input[CONF_TOKEN])):
                return self.async_update_reload_and_abort(
                    entry, unique_id=url, data={CONF_URL: url, CONF_TOKEN: user_input[CONF_TOKEN]}
                )
            errors["base"] = error

        schema = vol.Schema(
            {
                vol.Required(CONF_URL, default=entry.data[CONF_URL]): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
                ),
                vol.Required(CONF_TOKEN): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
            }
        )
        return self.async_show_form(step_id="reconfigure", data_schema=schema, errors=errors)

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return ClaudeVoiceOptionsFlow()


class ClaudeVoiceOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        # Claude must not be offered as its own fallback.
        own = er.async_get(self.hass).async_get_entity_id(
            "conversation", DOMAIN, self.config_entry.entry_id
        )

        opts = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_DOMAINS, default=opts.get(CONF_DOMAINS, DEFAULT_DOMAINS)
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=SELECTABLE_DOMAINS,
                        multiple=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(
                    CONF_SENSOR_CLASSES,
                    default=opts.get(CONF_SENSOR_CLASSES, DEFAULT_SENSOR_CLASSES),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=SENSOR_CLASSES,
                        multiple=True,
                        custom_value=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(
                    CONF_MAX_ENTITIES,
                    default=opts.get(CONF_MAX_ENTITIES, DEFAULT_MAX_ENTITIES),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=10, max=500, step=10, mode=selector.NumberSelectorMode.BOX
                    )
                ),
                vol.Required(
                    CONF_AREA_FIRST, default=opts.get(CONF_AREA_FIRST, DEFAULT_AREA_FIRST)
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_FALLBACK_AGENT,
                    description={"suggested_value": opts.get(CONF_FALLBACK_AGENT)},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="conversation", exclude_entities=[own] if own else []
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
