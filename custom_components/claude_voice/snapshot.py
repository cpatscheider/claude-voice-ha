"""Compact state snapshot for the <state> block, per the interface contract.

One line per entity, `Name|domain|state|key attrs`, grouped under `## <Area>` with the speaker's
area first. The formatting half is pure so it can be tested without Home Assistant; `collect()` is
the only part that touches HA.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

NO_AREA = "Ohne Raum"
SKIP_STATES = frozenset({"unavailable", "unknown"})


@dataclass(frozen=True)
class Row:
    area: str | None
    name: str
    domain: str
    state: str
    attrs: Mapping[str, Any]


def _num(value: Any) -> str | None:
    """Round to one decimal and drop a trailing .0. None if it is not a number."""
    if isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    r = round(f, 1)
    return str(int(r)) if r == int(r) else str(r)


def _with_unit(value: Any, unit: str | None) -> str | None:
    n = _num(value)
    if n is None:
        return None
    return f"{n}{unit}" if unit in ("°C", "°F", "%") else f"{n} {unit}" if unit else n


def describe(domain: str, state: str, attrs: Mapping[str, Any]) -> tuple[str, list[str]]:
    """Return (state, key attributes) for one entity, already rounded and unit-suffixed."""
    extras: list[str] = []
    unit = attrs.get("unit_of_measurement")

    if domain == "sensor":
        return _with_unit(state, unit) or state, extras

    if domain == "light" and state == "on":
        if (b := _num(attrs.get("brightness"))) is not None:
            extras.append(f"{round(float(b) / 255 * 100)}%")
    elif domain == "climate":
        temp_unit = attrs.get("temperature_unit") or "°C"
        if (cur := _with_unit(attrs.get("current_temperature"), temp_unit)) is not None:
            extras.append(f"ist {cur}")
        if (target := _with_unit(attrs.get("temperature"), temp_unit)) is not None:
            extras.append(f"soll {target}")
        if action := attrs.get("hvac_action"):
            extras.append(str(action))
    elif domain == "cover":
        if (pos := _num(attrs.get("current_position"))) is not None:
            extras.append(f"{pos}% offen")
    elif domain == "fan" and state == "on":
        if (pct := _num(attrs.get("percentage"))) is not None:
            extras.append(f"{pct}%")
    elif domain == "media_player" and state not in ("off", "standby"):
        if (vol := _num(attrs.get("volume_level"))) is not None:
            extras.append(f"Lautstärke {round(float(vol) * 100)}%")
        if title := attrs.get("media_title"):
            extras.append(str(title)[:60])
    elif domain == "weather":
        temp_unit = attrs.get("temperature_unit") or "°C"
        if (t := _with_unit(attrs.get("temperature"), temp_unit)) is not None:
            extras.append(t)
        if (h := _num(attrs.get("humidity"))) is not None:
            extras.append(f"Feuchte {h}%")
        if (w := _num(attrs.get("wind_speed"))) is not None:
            extras.append(f"Wind {w} {attrs.get('wind_speed_unit') or 'km/h'}")

    return state, extras


def line(row: Row) -> str:
    state, extras = describe(row.domain, row.state, row.attrs)
    name = row.name.replace("|", "/").replace("\n", " ").strip()
    parts = [name, row.domain, state]
    if extras:
        parts.append(", ".join(extras))
    return "|".join(parts)


def render(
    rows: Iterable[Row],
    speaker_area: str | None,
    *,
    area_first: bool = True,
    max_entities: int = 150,
) -> str:
    """Group, order and cap the rows. Rows in SKIP_STATES are dropped before the cap applies."""
    groups: dict[str, list[Row]] = {}
    for row in rows:
        if row.state in SKIP_STATES:
            continue
        groups.setdefault(row.area or NO_AREA, []).append(row)

    def order(area: str) -> tuple[int, str]:
        if area_first and speaker_area and area == speaker_area:
            return (0, "")
        if area == NO_AREA:
            return (2, "")
        return (1, area.casefold())

    out: list[str] = []
    budget = max_entities
    for area in sorted(groups, key=order):
        if budget <= 0:
            break
        members = sorted(groups[area], key=lambda r: (r.domain, r.name.casefold()))[:budget]
        budget -= len(members)
        out.append(f"## {area}")
        out.extend(line(r) for r in members)
    return "\n".join(out)


def collect(
    hass: HomeAssistant, domains: Iterable[str], sensor_classes: Iterable[str]
) -> list[Row]:
    """Rows for every entity in `domains` that is exposed to Assist."""
    from homeassistant.components.homeassistant.exposed_entities import (
        async_should_expose,
    )
    from homeassistant.helpers import (
        area_registry as ar,
        device_registry as dr,
        entity_registry as er,
    )

    areas = ar.async_get(hass)
    devices = dr.async_get(hass)
    entities = er.async_get(hass)
    sensor_classes = set(sensor_classes)

    rows: list[Row] = []
    for state in hass.states.async_all(list(domains)):
        if state.domain == "sensor" and state.attributes.get("device_class") not in sensor_classes:
            continue
        if not async_should_expose(hass, "conversation", state.entity_id):
            continue
        area_id = None
        if entry := entities.async_get(state.entity_id):
            area_id = entry.area_id
            if area_id is None and entry.device_id and (device := devices.async_get(entry.device_id)):
                area_id = device.area_id
        area = areas.async_get_area(area_id) if area_id else None
        rows.append(
            Row(
                area=area.name if area else None,
                name=state.name,
                domain=state.domain,
                state=state.state,
                attrs=state.attributes,
            )
        )
    return rows


def speaker_area(hass: HomeAssistant, device_id: str | None, satellite_id: str | None) -> str | None:
    """Area of the satellite that heard the request, if it has one."""
    from homeassistant.helpers import (
        area_registry as ar,
        device_registry as dr,
        entity_registry as er,
    )

    devices = dr.async_get(hass)
    area_id = None
    if satellite_id and (entry := er.async_get(hass).async_get(satellite_id)):
        area_id = entry.area_id
        if area_id is None and entry.device_id:
            device_id = device_id or entry.device_id
    if area_id is None and device_id and (device := devices.async_get(device_id)):
        area_id = device.area_id
    if area_id and (area := ar.async_get(hass).async_get_area(area_id)):
        return area.name
    return None
