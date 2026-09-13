import asyncio
import logging
import math
import time

import aiohttp
import pysma

try:
    from pysma.sma_webconnect import SMAWebConnect
except ImportError:
    SMAWebConnect = None

logger = logging.getLogger(__name__.rsplit(".")[-1])
SENSOR_NAMES = ("grid_power", "metering_power_supplied", "metering_power_absorbed")


class SMA:
    """Read SMA WebConnect using either pysma 0.7 or 1.x."""

    def __init__(self, master):
        self.master = master
        self.config = master.config
        self.configSMA = self.config.get("sources", {}).get("SMA", {})
        self.url = self.configSMA.get("url")
        self.user = self.configSMA.get("user", "user")
        self.password = self.configSMA.get("password")
        self.status = bool(self.configSMA.get("enabled", False) and self.url
                           and self.user and self.password)
        self.cacheTime = max(1, float(self.configSMA.get("cacheTime", 10)))
        self.timeout = max(1, float(self.configSMA.get("timeout", 30)))
        self.generatedW = self.consumedW = 0
        self.lastFetch = 0
        self._lastAttempt = None
        self.fetchFailed = False
        self.sensors = None
        if not self.status:
            self.master.releaseModule("lib.TWCManager.EMS", "SMA")

    def getConsumption(self):
        if self.status:
            self.update()
        return self.consumedW

    def getGeneration(self):
        if self.status:
            self.update()
        return self.generatedW

    async def getSensors(self):
        async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(
                ssl=self.configSMA.get("verifySSL", False)
            ),
            timeout=aiohttp.ClientTimeout(total=self.timeout),
        ) as session:
            client_class = SMAWebConnect or pysma.SMA
            client = client_class(session, self.url, password=self.password,
                                  group=self.user)
            await client.new_session()
            try:
                if SMAWebConnect is not None:
                    sensors = await client.get_sensors()
                    for sensor in sensors:
                        sensor.enabled = sensor.name in SENSOR_NAMES
                else:
                    sensors = pysma.Sensors()
                    for name in SENSOR_NAMES:
                        sensors.add(getattr(pysma.definitions, name))
                await client.read(sensors)
                return sensors
            finally:
                await client.close_session()

    async def _fetch(self):
        return await asyncio.wait_for(self.getSensors(), timeout=self.timeout)

    def update(self):
        now = time.monotonic()
        if not self.status or (self._lastAttempt is not None
                               and now - self._lastAttempt < self.cacheTime):
            return False
        self._lastAttempt = now
        try:
            sensors = asyncio.run(self._fetch())
            values = [float(sensors[name].value) for name in SENSOR_NAMES]
            if not all(math.isfinite(value) for value in values):
                raise ValueError("Non-finite SMA reading")
            generation, supplied, absorbed = values
            # Preserve the fork's import/export calculation.
            consumption = generation - supplied if supplied > absorbed else generation + absorbed
        except Exception as error:
            self.fetchFailed = True
            logger.warning("SMA poll failed (%s); retaining cached readings", type(error).__name__)
            return False
        self.sensors = sensors
        self.generatedW, self.consumedW = generation, consumption
        self.fetchFailed = False
        self.lastFetch = time.time()
        return True
