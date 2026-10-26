"""
EVSEInstance implementation for Tesla Wall Connector Generation 2 slave devices.

Extends TWCSlave with the unified EVSEInstance interface so that Gen2 TWCs can
participate in the controller-agnostic power distribution algorithm.

Ported from ngardiner/TWCManager#483 (MikeBishop); adapted for current main.
"""

import time

from TWCManager.EVSEInstance.EVSEInstance import EVSEInstance
from TWCManager.TWCSlave import TWCSlave


class Gen2TWC(EVSEInstance, TWCSlave):
    """A Gen2 TWC slave device managed over RS485.

    This class inherits all RS485 protocol behaviour from TWCSlave and adds
    the EVSEInstance interface on top, allowing the controller-agnostic power
    distribution loop to treat Gen2 devices the same as any other EVSE.
    """

    def __init__(self, TWCID, maxAmps, config, master):
        # Backing stores for properties that shadow TWCSlave class attributes.
        # These must be initialised before TWCSlave.__init__ runs so that any
        # property setter triggered during super().__init__ has somewhere to write.
        self._gen2_isCharging = 0
        self._gen2_currentVIN = ""

        # Per-EVSE amps target set by distributeEVSEPower() (Phase 4).
        # When not None, send_master_heartbeat() uses this value directly
        # instead of recomputing the per-car fair share.
        self._evseTargetAmps = None

        TWCSlave.__init__(self, TWCID, maxAmps, config, master)

    # ------------------------------------------------------------------
    # EVSEInstance: identity
    # ------------------------------------------------------------------

    @property
    def ID(self) -> str:
        return "Gen2TWC-%02X%02X" % (self.TWCID[0], self.TWCID[1])

    # ------------------------------------------------------------------
    # EVSEInstance: capabilities
    # ------------------------------------------------------------------

    @property
    def isReadOnly(self) -> bool:
        return False

    @property
    def isLocal(self) -> bool:
        return True

    # ------------------------------------------------------------------
    # EVSEInstance: state
    #
    # isCharging and currentVIN are class-level attributes on TWCSlave that
    # are mutated via plain assignment throughout the codebase.  We expose
    # them as properties with setters so existing code keeps working while
    # the EVSEInstance interface can read them polymorphically.
    # ------------------------------------------------------------------

    @property
    def isCharging(self) -> bool:
        return bool(self._gen2_isCharging)

    @isCharging.setter
    def isCharging(self, value):
        self._gen2_isCharging = value

    @property
    def currentVIN(self) -> str:
        return self._gen2_currentVIN

    @currentVIN.setter
    def currentVIN(self, value):
        self._gen2_currentVIN = value

    @property
    def wantsToCharge(self) -> bool:
        """Release a declined offer, periodically probing for renewed demand.

        State 03 can retain a nonzero advertised limit after the car stops.
        Give it ten seconds with usable power before lending its share, and
        retry after a minute so stopping our offer cannot strand the car.
        A change of state or resumed current immediately restores eligibility.
        """
        now = time.monotonic()
        if self.reportedState == 0x03 and self.reportedAmpsActual < 1:
            retry = getattr(self, "_idleRetryAt", 0)
            if now < retry:
                return False
            if retry:
                self._idleRetryAt = 0
                self._idleOfferSince = None
            since = getattr(self, "_idleOfferSince", None)
            if self.lastAmpsOffered >= self.minAmpsTWCSupports:
                if since is None:
                    self._idleOfferSince = now
                elif now - since >= 10:
                    self._idleRetryAt = now + 60
                    self._idleOfferSince = None
                    return False
            else:
                # Start the grace period only once the probe has capacity.
                self._idleOfferSince = None
            return True
        self._idleRetryAt = 0
        self._idleOfferSince = None
        if self.reportedState in (0x04, 0x08):
            return True
        return self.reportedAmpsMax > 0 or self.reportedAmpsActual > 0

    @property
    def currentAmps(self) -> float:
        return self.reportedAmpsActual

    @property
    def currentVoltage(self) -> list:
        """Per-phase voltages [A, B, C].  Falls back to configured default when
        the TWC has not yet reported voltage measurements."""
        phases = [self.voltsPhaseA, self.voltsPhaseB, self.voltsPhaseC]
        if not any(phases):
            default_v = self.configConfig.get("defaultVoltage", 240)
            count = self.configConfig.get("numberOfPhases", 1)
            phases = [default_v if i < count else 0 for i in range(3)]
        return phases

    @property
    def currentPower(self) -> float:
        return self.convertAmpsToWatts(self.reportedAmpsActual, self.currentVoltage)

    @property
    def minPower(self) -> float:
        return self.convertAmpsToWatts(self.minAmpsTWCSupports, self.currentVoltage)

    @property
    def maxPower(self) -> float:
        return self.convertAmpsToWatts(self.wiringMaxAmps, self.currentVoltage)

    # ------------------------------------------------------------------
    # EVSEInstance: controller membership
    # ------------------------------------------------------------------

    @property
    def controllers(self) -> list:
        return ["Gen2TWCs"]

    # ------------------------------------------------------------------
    # EVSEInstance: control
    #
    # setTargetPower / startCharging / stopCharging are stubs in Phase 2.
    # The full watt-based implementation arrives in Phase 4 when the
    # centralized power distribution loop replaces the per-slave heartbeat
    # amps calculation.
    # ------------------------------------------------------------------

    def setTargetPower(self, watts: float) -> None:
        """Convert watts to amps and store as the centralized amps target.

        Sets ``_evseTargetAmps`` which send_master_heartbeat() picks up in
        place of the per-car fair-share calculation, giving the centralized
        distributor full control over this slave's charge rate.
        """
        amps = self.convertWattsToAmps(watts, self.currentVoltage)
        self._evseTargetAmps = amps
        self.lastAmpsDesired = amps  # kept for compatibility / logging

    def startCharging(self) -> None:
        """Charging start is managed by the RS485 heartbeat cycle."""

    def stopCharging(self) -> None:
        """Charging stop is managed by the RS485 heartbeat cycle."""
