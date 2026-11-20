from custom_components.claude_voice.snapshot import NO_AREA, Row, describe, line, render


def test_light_brightness_as_percent():
    assert line(Row("Wohnzimmer", "Decke", "light", "on", {"brightness": 204})) == "Decke|light|on|80%"
    assert line(Row("Wohnzimmer", "Decke", "light", "off", {"brightness": 204})) == "Decke|light|off"


def test_sensor_rounds_and_carries_unit():
    assert describe("sensor", "18.24999", {"unit_of_measurement": "°C"}) == ("18.2°C", [])
    assert describe("sensor", "55.0", {"unit_of_measurement": "%"}) == ("55%", [])
    assert describe("sensor", "1234.56", {"unit_of_measurement": "W"}) == ("1234.6 W", [])
    assert describe("sensor", "open", {}) == ("open", [])


def test_climate_current_and_target():
    _, extras = describe(
        "climate",
        "heat",
        {"current_temperature": 18.24, "temperature": 21.0, "hvac_action": "heating"},
    )
    assert extras == ["ist 18.2°C", "soll 21°C", "heating"]


def test_weather_line():
    row = Row(None, "Forecast Home", "weather", "cloudy", {"temperature": 4.06, "humidity": 87})
    assert line(row) == "Forecast Home|weather|cloudy|4.1°C, Feuchte 87%"


def test_pipe_in_name_cannot_break_the_format():
    assert line(Row(None, "A|B", "switch", "on", {})) == "A/B|switch|on"


def test_bool_is_not_a_number():
    assert describe("sensor", True, {"unit_of_measurement": "°C"})[0] is True


def test_speaker_area_first_then_alphabetical_then_no_area():
    rows = [
        Row(None, "Forecast Home", "weather", "sunny", {}),
        Row("Küche", "Licht", "light", "off", {}),
        Row("Bad", "Licht", "light", "off", {}),
        Row("Wohnzimmer", "Decke", "light", "off", {}),
    ]
    out = render(rows, "Wohnzimmer").splitlines()
    assert [h for h in out if h.startswith("## ")] == [
        "## Wohnzimmer",
        "## Bad",
        "## Küche",
        f"## {NO_AREA}",
    ]
    assert render(rows, "Wohnzimmer", area_first=False).splitlines()[0] == "## Bad"


def test_unavailable_and_unknown_are_skipped_before_the_cap():
    rows = [Row("Bad", f"T{i}", "sensor", "unavailable", {}) for i in range(5)] + [
        Row("Bad", "Ok", "sensor", "18", {"unit_of_measurement": "°C"}),
        Row("Bad", "Unk", "sensor", "unknown", {}),
    ]
    assert render(rows, None, max_entities=1) == "## Bad\nOk|sensor|18°C"


def test_cap_keeps_the_speakers_area():
    rows = [Row("Bad", f"L{i}", "light", "off", {}) for i in range(5)] + [
        Row("Wohnzimmer", "Decke", "light", "on", {})
    ]
    out = render(rows, "Wohnzimmer", max_entities=2)
    assert out == "## Wohnzimmer\nDecke|light|on\n## Bad\nL0|light|off"


def test_empty():
    assert render([], "Bad") == ""
