import logging
import requests
import time
import asyncio

import aiohttp

import pysma



logger = logging.getLogger(__name__.rsplit(".")[-1])

class SMA:

    # SMA EMS Module
    # Fetches Consumption and Generation details from SMA WebConnect

    cacheTime = 10  # in seconds
    config = None
    configConfig = None
    configSMA = None
    consumedW = 0
    fetchFailed = False
    generatedW = 0
    lastFetch = 0
    master = None
    status = False
    url = None
    user = None
    password = None
    sma = None
    sensors = None

    def __init__(self, master):
        self.master = master
        self.config = master.config
        try:
            self.configConfig = master.config["config"]
        except KeyError:
            self.configConfig = {}
        try:
            self.configSMA = master.config["sources"]["SMA"]
        except KeyError:
            self.configSMA = {}
        self.status = self.configSMA.get("enabled", False)
        self.url = self.configSMA.get("url", None)
        self.user = self.configSMA.get("user", "user")
        self.password = self.configSMA.get("password", None)

        # Unload if this module is disabled or misconfigured
        if (not self.status) or (not self.url) or (not self.user) or (not
        self.password):
            self.master.releaseModule("lib.TWCManager.EMS", "SMA")
            return None

    def getConsumption(self):

        if not self.status:
            logger.debug("SMA EMS Module Disabled. Skipping getConsumption")
            return 0

        # Perform updates if necessary
        self.update()

        # Return consumption value
        return self.consumedW

    def getGeneration(self):

        if not self.status:
            logger.debug("SMA EMS Module Disabled. Skipping getGeneration")
            return 0

        # Perform updates if necessary
        self.update()

        # Return generation value
        return self.generatedW

    async def getSensors(self):

        async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=False)
        ) as session:
            self.fetchFailed = False
            self.sma = pysma.SMA(session, self.url,
            password=self.password, group=self.user)

            try:
                await self.sma.new_session()
            except pysma.exceptions.SmaAuthenticationException:
                logger.warning("Authentication failed!")
                self.fetchFailed = True
                return
            except pysma.exceptions.SmaConnectionException:
                logger.warning("Unable to connect to device at %s",
                self.url)
                self.fetchFailed = True
                return

            # We should not get any exceptions, but if we do we will close the session.
            try:
                self.sensors = pysma.Sensors()
                self.sensors.add(pysma.definitions.grid_power)
                self.sensors.add(pysma.definitions.metering_current_consumption)
                await self.sma.read(self.sensors)
            except:
                logger.warning("Sensor request failed!")
                self.fetchFailed = True
            finally:
                logger.info("Closing Session...")
                await self.sma.close_session()


    def update(self):
        # Update function - determine if an update is required

        if (int(time.time()) - self.lastFetch) > self.cacheTime:
            # Cache has expired. Fetch values from SMA
            asyncio.run(self.getSensors())

            for sen in self.sensors:
                if sen.value is None:
                    logger.debug("{:>25}".format(sen.name))
                else:
                    logger.debug("{:>25}{:>15} {}".format(sen.name, str(sen.value), sen.unit))

            if self.fetchFailed is not True:
                if self.sensors["metering_current_consumption"].value is not None:
                    self.consumedW = self.sensors["metering_current_consumption"].value
                    logger.debug("SMA getConsumption returns " + str(self.consumedW))
                else:
                    logger.debug(
                        "SMA getConsumption fetch failed, using cached values"
                    )
                if self.sensors["grid_power"].value is not None:
                    self.generatedW = self.sensors["grid_power"].value
                    logger.debug("SMA getGeneration returns " + str(self.generatedW))
                else:
                    logger.debug(
                        "SMA getGeneration data fetch failed, using cached values"
                    )
            else:
                logger.debug(
                    "SMA data fetch failed, using cached values"
                )

            # Update last fetch time
            if self.fetchFailed is not True:
                self.lastFetch = int(time.time())

            return True
        else:
            # Cache time has not elapsed since last fetch, serve from cache.
            return False
