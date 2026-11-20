"""Conversation entity: streams the sidecar's answer into the ChatLog, falls back on failure."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Literal

from homeassistant.components import conversation
from homeassistant.const import MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import ClaudeVoiceConfigEntry
from .client import Delta, Done, SidecarError, ToolUse
from .const import (
    CONF_AREA_FIRST,
    CONF_DOMAINS,
    CONF_FALLBACK_AGENT,
    CONF_MAX_ENTITIES,
    CONF_SENSOR_CLASSES,
    DEFAULT_AREA_FIRST,
    DEFAULT_DOMAINS,
    DEFAULT_MAX_ENTITIES,
    DEFAULT_SENSOR_CLASSES,
    DOMAIN,
    LOGGER,
    UNREACHABLE_MESSAGE,
)
from .snapshot import collect, render, speaker_area


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ClaudeVoiceConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([ClaudeVoiceEntity(entry)])


class ClaudeVoiceEntity(conversation.ConversationEntity, conversation.AbstractConversationAgent):
    """Claude, driven through the sidecar."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supports_streaming = True
    # Claude acts through HA's MCP server itself, so from HA's point of view it controls devices.
    _attr_supported_features = conversation.ConversationEntityFeature.CONTROL

    def __init__(self, entry: ClaudeVoiceConfigEntry) -> None:
        self.entry = entry
        self._attr_unique_id = entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Claude Voice",
            manufacturer="claude-voice-sidecar",
            entry_type=DeviceEntryType.SERVICE,
        )
        self._last: dict[str, Any] = {}

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        return MATCH_ALL

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._last

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        conversation.async_set_agent(self.hass, self.entry, self)

    async def async_will_remove_from_hass(self) -> None:
        conversation.async_unset_agent(self.hass, self.entry)
        await super().async_will_remove_from_hass()

    def _opt(self, key: str, default: Any) -> Any:
        return self.entry.options.get(key, default)

    def _build_body(self, user_input: conversation.ConversationInput, conversation_id: str) -> dict:
        area = speaker_area(self.hass, user_input.device_id, user_input.satellite_id)
        rows = collect(
            self.hass,
            self._opt(CONF_DOMAINS, DEFAULT_DOMAINS),
            self._opt(CONF_SENSOR_CLASSES, DEFAULT_SENSOR_CLASSES),
        )
        snapshot = render(
            rows,
            area,
            area_first=self._opt(CONF_AREA_FIRST, DEFAULT_AREA_FIRST),
            max_entities=int(self._opt(CONF_MAX_ENTITIES, DEFAULT_MAX_ENTITIES)),
        )
        return {
            # The chat log's id is the HA conversation id; the sidecar maps it 1:1 to a CLI session.
            "conversation_id": conversation_id,
            "text": user_input.text,
            "language": user_input.language,
            "context": {
                "area": area,
                "now": dt_util.now().isoformat(timespec="seconds"),
            },
            "snapshot": snapshot or None,
        }

    async def _async_handle_message(
        self,
        user_input: conversation.ConversationInput,
        chat_log: conversation.ChatLog,
    ) -> conversation.ConversationResult:
        body = self._build_body(user_input, chat_log.conversation_id)
        state: dict[str, Any] = {"streamed": False, "error": None, "done": None, "tools": []}

        async def deltas() -> AsyncIterator[conversation.AssistantContentDeltaDict]:
            yield {"role": "assistant"}
            try:
                async for event in self.entry.runtime_data.turn(body):
                    if isinstance(event, Delta):
                        state["streamed"] = True
                        yield {"content": event.text}
                    elif isinstance(event, ToolUse):
                        state["tools"].append(event.name)
                    elif isinstance(event, Done):
                        state["done"] = event
                        # Some turns finish without deltas (rare, but the contract allows it).
                        if not state["streamed"] and event.text:
                            state["streamed"] = True
                            yield {"content": event.text}
            except SidecarError as err:
                # Ending the stream normally keeps whatever was already spoken in the chat log.
                # Raising here would drop it, and the listener has already sent it to TTS.
                state["error"] = err

        async for _content in chat_log.async_add_delta_content_stream(self.entity_id, deltas()):
            pass

        err: SidecarError | None = state["error"]
        done: Done | None = state["done"]
        self._record(done, err, state["tools"])

        if err is None and state["streamed"]:
            return conversation.async_get_result_from_chat_log(user_input, chat_log)

        if err is not None:
            LOGGER.warning("Claude turn failed (%s), streamed=%s", err, state["streamed"])
        if state["streamed"]:
            # The answer broke off mid-sentence. Handing the turn to another agent now would make
            # the speaker say two different answers, so keep the partial one.
            return conversation.async_get_result_from_chat_log(user_input, chat_log)

        return await self._fallback(user_input, chat_log)

    async def _fallback(
        self,
        user_input: conversation.ConversationInput,
        chat_log: conversation.ChatLog,
    ) -> conversation.ConversationResult:
        agent_id = self._opt(CONF_FALLBACK_AGENT, None)
        if agent_id and agent_id != self.entity_id:
            LOGGER.info("Handing the turn to fallback agent %s", agent_id)
            try:
                # Same conversation id: HA hands the fallback agent this very chat log (it is the
                # active one in this context), so its answer streams to the same TTS listener.
                result = await conversation.async_converse(
                    self.hass,
                    user_input.text,
                    chat_log.conversation_id,
                    user_input.context,
                    language=user_input.language,
                    agent_id=agent_id,
                    device_id=user_input.device_id,
                    satellite_id=user_input.satellite_id,
                )
            except Exception:  # noqa: BLE001 - a broken fallback must still produce speech
                LOGGER.exception("Fallback agent %s failed", agent_id)
            else:
                self._last = {**self._last, "last_fallback": agent_id}
                self.async_write_ha_state()
                return result

        chat_log.async_add_assistant_content_without_tools(
            conversation.AssistantContent(agent_id=self.entity_id, content=UNREACHABLE_MESSAGE)
        )
        return conversation.async_get_result_from_chat_log(user_input, chat_log)

    def _record(self, done: Done | None, err: SidecarError | None, tools: list[str]) -> None:
        latency = done.latency_ms if done else {}
        self._last = {
            "last_error": err.code if err else None,
            "last_first_delta_ms": latency.get("first_delta_ms"),
            "last_total_ms": latency.get("total_ms"),
            "last_tools": tools,
            "last_fallback": None,
        }
        self.async_write_ha_state()
