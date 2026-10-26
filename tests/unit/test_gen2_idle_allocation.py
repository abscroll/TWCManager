"""Exercise idle lending and asynchronous RS485 handoffs with real Gen2 objects."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from TWCManager.EVSEInstance.Gen2TWC import Gen2TWC
from TWCManager.TWCMaster import TWCMaster


def setup_pair():
    master = TWCMaster.__new__(TWCMaster)
    master.config = {
        "config": {
            "defaultVoltage": 240,
            "numberOfPhases": 1,
            "wiringMaxAmpsAllTWCs": 32,
        }
    }
    chargers = []
    for identifier, state, actual in (("5989", 1, 16), ("3156", 3, 0)):
        evse = Gen2TWC.__new__(Gen2TWC)
        evse.TWCID = bytes.fromhex(identifier)
        evse.master = master
        evse.config = master.config
        evse.configConfig = master.config["config"]
        evse.wiringMaxAmps = 32
        evse.minAmpsTWCSupports = 6
        evse.protocolVersion = 2
        evse.reportedState = state
        evse.reportedAmpsActual = actual
        evse.reportedAmpsMax = evse.lastAmpsOffered = 16
        evse.voltsPhaseA = 240
        evse.voltsPhaseB = evse.voltsPhaseC = 0
        chargers.append(evse)
    master.getSlaveTWCs = lambda: chargers
    master.getDedupedEVSEs = lambda: chargers
    controller = SimpleNamespace(maxPower=32 * 240)
    master.getModulesByType = lambda kind: (
        [
            {"name": "Gen2TWCs", "ref": controller},
            {"name": "TeslaAPIController", "ref": controller},
        ]
        if kind == "EVSEController"
        else []
    )
    master.getMaxAmpsToDivideAmongSlaves = lambda: 32
    return master, chargers


def send(evse):
    offer = evse.set_last_amps_offered(evse._evseTargetAmps)
    payload = evse._amps_heartbeat(offer)
    if payload[0] == 0:
        return evse.reportedAmpsMax
    return int.from_bytes(payload[1:3], "big") / 100


def release_idle(master, active, idle, clock):
    clock.return_value = 100
    master.distributeEVSEPower()
    clock.return_value = 111
    master.distributeEVSEPower()
    assert idle._evseTargetAmps == 0
    assert active._evseTargetAmps == 32
    # Merely queuing the idle reduction must NOT release its acknowledged 16A.
    assert send(idle) == 0
    assert send(active) == 16
    idle.reportedAmpsMax = 0  # RS485 acknowledgement
    assert send(active) == 32
    active.reportedAmpsMax = active.reportedAmpsActual = 32


@pytest.mark.parametrize("order", [(0, 1), (1, 0)])
def test_idle_releases_full_32a_then_resume_rebalances_safely(order):
    master, (active, idle) = setup_pair()
    with patch("TWCManager.EVSEInstance.Gen2TWC.time.monotonic") as clock:
        release_idle(master, active, idle, clock)
        clock.return_value = 120
        master.distributeEVSEPower()
        assert active._evseTargetAmps == 32
        assert idle._evseTargetAmps == 0
        # The second car wakes before its periodic retry, requesting charge.
        idle.reportedState = 4
        master.distributeEVSEPower()
        assert [active._evseTargetAmps, idle._evseTargetAmps] == [16, 16]
        for index in order:
            send((active, idle)[index])
        assert idle.lastAmpsOffered == 0
        assert active.lastAmpsOffered == 16
        assert send(idle) == 0  # old active limit has not been acknowledged
        active.reportedAmpsMax = 16
        assert send(idle) == 0  # active car still drawing its former 32A
        active.reportedAmpsActual = 16
        assert send(idle) == 16
        idle.reportedAmpsMax = idle.reportedAmpsActual = 16
        idle.reportedState = 1
        assert active.reportedAmpsActual + idle.reportedAmpsActual == 32


def test_periodic_probe_recovers_without_state_change():
    master, (active, idle) = setup_pair()
    with patch("TWCManager.EVSEInstance.Gen2TWC.time.monotonic") as clock:
        release_idle(master, active, idle, clock)
        clock.return_value = 170
        master.distributeEVSEPower()
        assert idle._evseTargetAmps == 0
        clock.return_value = 171
        master.distributeEVSEPower()
        assert [active._evseTargetAmps, idle._evseTargetAmps] == [16, 16]
        assert send(idle) == 0
        assert send(active) == 16
        # A probe waiting for capacity must not time out before it can start.
        clock.return_value = 200
        master.distributeEVSEPower()
        assert idle._evseTargetAmps == 16
        active.reportedAmpsMax = active.reportedAmpsActual = 16
        assert send(idle) == 16
        idle.reportedAmpsMax = 16
        clock.return_value = 201
        master.distributeEVSEPower()
        clock.return_value = 212
        master.distributeEVSEPower()
        assert idle._evseTargetAmps == 0  # declined again: release its share
        assert active._evseTargetAmps == 32


def test_no_grace_reservation_for_unplugged_car():
    master, (active, idle) = setup_pair()
    idle.reportedState = 0
    idle.reportedAmpsMax = idle.lastAmpsOffered = 0
    master.distributeEVSEPower()
    assert active._evseTargetAmps == 32
    assert idle._evseTargetAmps == 0


def test_idle_does_not_lose_share_during_initial_grace():
    master, (_, idle) = setup_pair()
    with patch("TWCManager.EVSEInstance.Gen2TWC.time.monotonic") as clock:
        for now in (100, 105, 109):
            clock.return_value = now
            master.distributeEVSEPower()
            assert idle._evseTargetAmps == 16


def test_merged_api_stopped_state_cannot_restore_idle_reservation():
    from TWCManager.EVSEInstance.MergedEVSE import MergedEVSE

    master, (active, idle) = setup_pair()
    api = SimpleNamespace(isLocal=False, wantsToCharge=True)
    merged = MergedEVSE(master, idle, api)
    with patch("TWCManager.EVSEInstance.Gen2TWC.time.monotonic") as clock:
        release_idle(master, active, idle, clock)
        assert not merged.wantsToCharge
        idle.reportedState = 4
        assert merged.wantsToCharge


def test_resumed_current_cancels_idle_backoff():
    master, (active, idle) = setup_pair()
    with patch("TWCManager.EVSEInstance.Gen2TWC.time.monotonic") as clock:
        release_idle(master, active, idle, clock)
        idle.reportedAmpsActual = 1
        master.distributeEVSEPower()
        assert idle._evseTargetAmps == 16


def test_less_than_minimum_free_capacity_stays_off():
    master, (active, idle) = setup_pair()
    active.reportedAmpsMax = active.reportedAmpsActual = active.lastAmpsOffered = 29
    idle.reportedAmpsMax = idle.lastAmpsOffered = 0
    idle._evseTargetAmps = 16
    assert send(idle) == 0  # never force 6A when only 3A is free
