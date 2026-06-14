"""Field fix (2026-06-14) — Papouch TME with older firmware.

The unit at cabinet MAR_KRK_ORM_01 (192.168.1.254) returns HTTP 404 on
`/values.xml` and instead serves `/fresh.xml` with an attribute-based format:

    <sns ... status="0" unit="0" val="285" .../>

where `val` is temperature × 10 (285 -> 28.5 C) and `unit` codes 0/1/2 = C/F/K.

These tests pin the `/fresh.xml` fallback in discovery.check_tme_sensor and the
read_tme_temperature poll path, plus confirm the newer `/values.xml` element
format still parses (no regression).
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch


# Real capture from the field device (192.168.1.254).
FRESH_XML = (
    '<?xml version="1.0" encoding="iso-8859-1"?>\n'
    '<root xmlns="http://www.papouch.com/xml/TME/act">\n'
    '<sns id="1" type="4" location="Thermometer" status="0" hi="0" lo="0" '
    'unit="0" val="285" min="-9999" max="9999"/>'
    '<status location="Thermometer" mac="0080A3769685" /></root>'
)

# Newer-firmware element format served on /values.xml.
VALUES_XML = "<root><sns><sn0><v>23.5</v><u>C</u></sn0></sns></root>"


class _Resp:
    def __init__(self, status_code: int, text: str, content_type: str = "text/xml"):
        self.status_code = status_code
        self.text = text
        self.headers = {"content-type": content_type}


class _FakeClient:
    """Stand-in for httpx.AsyncClient that answers based on the requested URL."""

    def __init__(self, values_status=404, values_body="ERROR 404",
                 fresh_status=200, fresh_body=FRESH_XML):
        self._v = (values_status, values_body)
        self._f = (fresh_status, fresh_body)

    # Allow `httpx.AsyncClient(timeout=1.5)` then `async with ... as client`.
    def __call__(self, *a, **k):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url: str):
        if url.endswith("/values.xml"):
            return _Resp(*self._v)
        if url.endswith("/fresh.xml"):
            return _Resp(*self._f)
        return _Resp(404, "")


def test_check_tme_sensor_parses_fresh_xml():
    from app.services import discovery
    with patch("httpx.AsyncClient", _FakeClient()):
        res = asyncio.run(discovery.check_tme_sensor("192.168.1.254", 80))
    assert res is not None, "fresh.xml device not recognised"
    assert res["temperature"] == 28.5          # 285 / 10
    assert res["unit"] == "C"                   # unit code 0
    assert res["type"] == "temp_sensor_tme"
    assert res["port"] == 80


def test_read_tme_temperature_via_fresh_xml():
    from app.services import discovery
    with patch("httpx.AsyncClient", _FakeClient()):
        val = asyncio.run(discovery.read_tme_temperature("192.168.1.254"))
    assert val == 28.5


def test_values_xml_still_parses_no_regression():
    from app.services import discovery
    fake = _FakeClient(values_status=200, values_body=VALUES_XML)
    with patch("httpx.AsyncClient", fake):
        res = asyncio.run(discovery.check_tme_sensor("192.168.1.190", 80))
    assert res is not None
    assert res["temperature"] == 23.5
    assert res["unit"] == "C"


def test_unrecognised_device_returns_none():
    from app.services import discovery
    fake = _FakeClient(values_status=404, values_body="nope",
                       fresh_status=404, fresh_body="nope")
    with patch("httpx.AsyncClient", fake):
        res = asyncio.run(discovery.check_tme_sensor("192.168.1.1", 80))
    assert res is None
