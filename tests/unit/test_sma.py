import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from TWCManager.EMS import SMA as module


def make_sma():
    return module.SMA(SimpleNamespace(config={"sources": {"SMA": {
        "enabled": True, "url": "https://inverter.invalid",
        "password": "test", "timeout": 1
    }}}, releaseModule=Mock()))


@pytest.mark.parametrize("supplied,absorbed,expected", [(500, 0, 1500), (0, 500, 2500)])
def test_readings_and_cache(supplied, absorbed, expected):
    sma = make_sma()
    sensors = dict(zip(module.SENSOR_NAMES, [
        SimpleNamespace(value=v) for v in (2000, supplied, absorbed)]))
    sma.getSensors = AsyncMock(return_value=sensors)
    assert sma.getGeneration() == 2000
    assert sma.getConsumption() == expected
    sma.getSensors.assert_awaited_once()


@pytest.mark.parametrize("error", [TimeoutError(), ValueError(), ConnectionError()])
def test_failure_preserves_cache_and_backs_off(error):
    sma = make_sma()
    sma.generatedW, sma.consumedW = 2000, 1500
    sma.getSensors = AsyncMock(side_effect=error)
    assert not sma.update()
    assert sma.fetchFailed
    assert sma.getGeneration() == 2000
    assert sma.getConsumption() == 1500
    sma.getSensors.assert_awaited_once()


def test_first_failure():
    sma = make_sma()
    sma.getSensors = AsyncMock(side_effect=ConnectionError())
    assert sma.getGeneration() == 0
    assert sma.fetchFailed


@pytest.mark.parametrize("value", [None, float("nan"), float("inf")])
def test_invalid_readings_do_not_replace_cache(value):
    sma = make_sma()
    sma.generatedW = 100
    sma.getSensors = AsyncMock(return_value={
        name: SimpleNamespace(value=value) for name in module.SENSOR_NAMES})
    assert not sma.update()
    assert sma.generatedW == 100


def test_real_library_api_with_mock_transport(monkeypatch):
    sma = make_sma()
    cls = module.SMAWebConnect or module.pysma.SMA
    monkeypatch.setattr(cls, "new_session", AsyncMock())
    close = AsyncMock()
    monkeypatch.setattr(cls, "close_session", close)
    sensors = (module.pysma.sma_webconnect.Sensors() if module.SMAWebConnect
               else module.pysma.Sensors())
    if module.SMAWebConnect:
        monkeypatch.setattr(cls, "get_sensors", AsyncMock(return_value=sensors))
    monkeypatch.setattr(cls, "read", AsyncMock())
    asyncio.run(sma.getSensors())
    close.assert_awaited_once()
