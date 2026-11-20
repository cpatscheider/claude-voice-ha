# Claude Voice for Home Assistant

A conversation agent for Home Assistant that sends each turn to the
claude-voice sidecar. The sidecar
runs the official Claude Code CLI on a Claude Pro login and acts on the house through HA's MCP
server. This integration only builds the turn, streams the answer back into Assist, and hands the
turn to a fallback agent when Claude is not available.

The sidecar and the build plan (design, interface contract, measurements) live in a private
repository; this one only holds the integration.

## What it does per turn

1. Builds a compact `<state>` snapshot: entities **exposed to Assist** in the configured domains,
   one line each (`Name|domain|state|key attrs`), grouped by area with the speaker's area first.
   Sensors are limited to the configured device classes; `unavailable`/`unknown` are skipped.
2. Sends text, language, `context` (speaker's area from the satellite, current time) and the
   snapshot to `POST /v1/turn`. The HA `conversation_id` maps 1:1 to a sidecar session.
3. Streams `delta` events into the ChatLog, so TTS starts speaking before the turn ends.
4. On `error` (timeout, cli_down, auth_expired, rate_limited, busy) or an unreachable sidecar,
   *before anything was spoken*: hands the turn to the fallback agent in the same chat log, or
   says "Claude ist gerade nicht erreichbar." An answer that breaks off mid-stream is kept as is
   rather than followed by a second answer from another agent.

The entity's attributes carry the last turn's `last_error`, `last_first_delta_ms`,
`last_total_ms`, `last_tools` and `last_fallback`.

## Install

HACS → Custom repositories → add `https://github.com/cpatscheider/claude-voice-ha` as type *Integration*, install
**Claude Voice**, restart Home Assistant. Then Settings → Devices & services → Add integration →
Claude Voice. In-cluster the URL is `http://claude-voice.default.svc.cluster.local:8765`; the
token is the sidecar's `SIDECAR_TOKEN`.

Options: snapshot domains, sensor device classes, max entities, speaker area first, and the
fallback agent (e.g. `conversation.google_ai_conversation`).

## Develop

Tests run against a real Home Assistant core and a fake sidecar speaking the contract over HTTP.
Requires Python ≥ 3.13.

```sh
python -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt
pip install hassil home-assistant-intents gazetteer-matcher   # conversation's own requirements
python -m pytest -q
```

Bump `version` in `custom_components/claude_voice/manifest.json` with every change and tag the
release `v<version>`, so HACS offers it as an update.
