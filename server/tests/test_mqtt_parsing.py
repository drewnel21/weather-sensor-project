import json

from app.mqtt_client import (
    MAX_CLOCK_SKEW_S,
    authoritative_ts,
    parse_reading,
    parse_status,
    parse_topic,
)


class TestParseTopic:
    def test_state(self):
        assert parse_topic("weather/pico-abc/state", "weather") == ("pico-abc", "state")

    def test_status(self):
        assert parse_topic("weather/pico-abc/status", "weather") == ("pico-abc", "status")

    def test_wrong_prefix(self):
        assert parse_topic("other/pico-abc/state", "weather") is None

    def test_unknown_kind(self):
        # state/status only; anything else is rejected so we don't end up
        # accidentally storing readings from a debug topic.
        assert parse_topic("weather/pico-abc/debug", "weather") is None

    def test_extra_segments(self):
        assert parse_topic("weather/pico-abc/state/extra", "weather") is None

    def test_empty_sensor_id(self):
        assert parse_topic("weather//state", "weather") is None

    def test_prefix_only(self):
        assert parse_topic("weather", "weather") is None


class TestParseReading:
    def test_valid_full(self):
        payload = json.dumps({
            "ts": 1700000000,
            "temperature_c": 20.1,
            "humidity": 50.0,
            "pressure_hpa": 1010.0,
            "rssi": -60,
        }).encode()
        r = parse_reading(payload)
        assert r is not None
        assert r.ts == 1700000000
        assert r.temperature_c == 20.1

    def test_valid_minimal(self):
        r = parse_reading(b'{"ts": 1}')
        assert r is not None and r.ts == 1

    def test_invalid_json(self):
        assert parse_reading(b"not json") is None

    def test_missing_ts(self):
        assert parse_reading(b'{"temperature_c": 20}') is None

    def test_wrong_type(self):
        assert parse_reading(b'{"ts": "not-an-int"}') is None


class TestParseStatus:
    def test_online_full(self):
        s = parse_status(b'{"online": true, "ip": "192.168.1.42", "fw": "0.1.0"}')
        assert s is not None
        assert s.online is True
        assert s.ip == "192.168.1.42"
        assert s.fw == "0.1.0"

    def test_offline_minimal(self):
        # The broker-published LWT typically carries just `online: false` and
        # whatever the firmware set as the LWT body — must parse cleanly.
        s = parse_status(b'{"online": false}')
        assert s is not None
        assert s.online is False
        assert s.ip is None

    def test_empty_payload(self):
        # Empty LWT is suspicious; we discard rather than guess "offline".
        assert parse_status(b"") is None

    def test_invalid_json(self):
        assert parse_status(b"not json") is None

    def test_missing_online(self):
        assert parse_status(b'{"ip": "1.2.3.4"}') is None


class TestAuthoritativeTs:
    # A representative "now" (2026-06-05-ish) for the server clock.
    NOW = 1_780_000_000

    def test_keeps_plausible_device_ts(self):
        # Device clock within a few seconds of ours (healthy NTP sync) — keep it.
        device = self.NOW - 3
        assert authoritative_ts(device, self.NOW) == device

    def test_overrides_year_2000_ntp_failure(self):
        # RP2040 with failed NTP: time anchored near the 2000-01-01 epoch.
        # Unix epoch for 2000-01-01 is 946684800; a freshly booted board lands
        # just above it. Must be replaced with the server receive time.
        device = 946_684_800 + 120
        assert authoritative_ts(device, self.NOW) == self.NOW

    def test_overrides_far_future_ts(self):
        # Defensive: a garbage clock in the future is just as wrong as the past.
        device = self.NOW + 10 * 365 * 86400
        assert authoritative_ts(device, self.NOW) == self.NOW

    def test_boundary_within_skew_is_kept(self):
        device = self.NOW - MAX_CLOCK_SKEW_S
        assert authoritative_ts(device, self.NOW) == device

    def test_boundary_just_over_skew_is_overridden(self):
        device = self.NOW - (MAX_CLOCK_SKEW_S + 1)
        assert authoritative_ts(device, self.NOW) == self.NOW
