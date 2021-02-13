# ConsoleLogging module. Provides output to console for logging.
import logging

from sys import modules
from termcolor import colored
from ww import f


logger = logging.getLogger(__name__.rsplit(".")[-1])


class ConsoleLogging:

    capabilities = {"queryGreenEnergy": False}
    config = None
    configConfig = None
    configLogging = None
    status = True

    def __init__(self, master):
        self.master = master
        self.config = master.config
        try:
            self.configConfig = master.config["config"]
        except KeyError:
            self.configConfig = {}
        try:
            self.configLogging = master.config["logging"]["Console"]
        except KeyError:
            self.configLogging = {}
        self.status = self.configLogging.get("enabled", True)

        # Unload if this module is disabled or misconfigured
        if not self.status:
            self.master.releaseModule("lib.TWCManager.Logging", "ConsoleLogging")
            return None

        # Initialize the mute config tree if it is not already
        if not self.configLogging.get("mute", None):
            self.configLogging["mute"] = {}

    def getCapabilities(self, capability):
        # Allows query of module capabilities when deciding which Logging module to use
        return self.capabilities.get(capability, False)

    def slavePower(self, data):
        # Not yet implemented
        return None

    def slaveStatus(self, data):
        # Check if this status is muted
        if self.configLogging["mute"].get("SlaveStatus", 0):
            return None

        logger.info(
            "Slave TWC %02X%02X: Delivered %d kWh, voltage per phase: (%d, %d, %d)."
            % (
                data["TWCID"][0],
                data["TWCID"][1],
                data["kWh"],
                data["voltsPerPhase"][0],
                data["voltsPerPhase"][1],
                data["voltsPerPhase"][2],
            )
        )

    def startChargeSession(self, data):
        # Check if this status is muted
        if self.configLogging["mute"].get("ChargeSessions", 0):
            return None

        # Called when a Charge Session Starts.
        twcid = "%02X%02X" % (data["TWCID"][0], data["TWCID"][0])
        logger.info("Charge Session Started for Slave TWC %s" % twcid)

    def stopChargeSession(self, data):
        # Check if this status is muted
        if self.configLogging["mute"].get("ChargeSessions", 0):
            return None

        # Called when a Charge Session Ends.
        twcid = "%02X%02X" % (data["TWCID"][0], data["TWCID"][0])
        logger.info("Charge Session Stopped for Slave TWC %s" % twcid)

    def updateChargeSession(self, data):
        # Check if this status is muted
        if self.configLogging["mute"].get("ChargeSessions", 0):
            return None

        # Called when additional information needs to be updated for a
        # charge session. For console output, we ignore this.
        return None
