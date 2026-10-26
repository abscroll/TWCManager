"""Gen2-only systems must use the 1.3.4 measured-current heartbeat allocator."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from TWCManager.EVSEInstance.Gen2TWC import Gen2TWC
from TWCManager.EVSEInstance.MergedEVSE import MergedEVSE
from TWCManager.TWCMaster import TWCMaster


def setup_pair():
    master = TWCMaster.__new__(TWCMaster)
    master.config = {
        "config": {
            "defaultVoltage": 240,
            "numberOfPhases": 1,
            "wiringMaxAmpsAllTWCs": 32,
            "wiringMaxAmpsPerTWC": 32,
            "minAmpsPerTWC": 6,
            "fakeMaster": True,
        }
    }
    master.settings = {"chargeRateControl": 1}
    master.queue_background_task = Mock()
    master.queue_vehicle_command = Mock()
    master.recordVehicleSessionStart = Mock()
    master.recordVehicleSessionEnd = Mock()
    master.updateVINStatus = Mock()
    master.cancelStopCarsCharging = Mock()
    master.getMasterHeartbeatOverride = lambda: b""
    master.getAllowedFlex = lambda: 0
    master.getSpikeAmps = lambda: 16
    policy = SimpleNamespace(policyIsGreen=lambda: False, fireWebhook=Mock())
    master.getModuleByName = lambda name: policy if name == "Policy" else None
    chargers = []
    for identifier in ("5989", "3156"):
        evse = Gen2TWC(bytes.fromhex(identifier), 32, master.config, master)
        evse.protocolVersion = 2
        evse.vehicleRateRaised = True
        evse.getLastVehicle = lambda: None
        evse.print_status = Mock()
        evse.reportedAmpsActual = 0
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


def heartbeat(evse, state, actual):
    limit = int(evse.lastAmpsOffered * 100)
    amps = int(actual * 100)
    payload = bytes([state, limit >> 8, limit & 255, amps >> 8, amps & 255, 0, 0, 0, 0])
    evse.receive_slave_heartbeat(payload)
    command = evse.masterHeartbeatData
    if command[0]:
        assert int.from_bytes(command[1:3], "big") / 100 == evse.lastAmpsOffered
    return evse.lastAmpsOffered


def test_registered_but_unused_api_controller_does_not_split_gen2_budget():
    master, chargers = setup_pair()
    for evse in chargers:
        evse._evseTargetAmps = 16
    master.distributeEVSEPower()
    assert all(e._evseTargetAmps is None for e in chargers)


@pytest.mark.parametrize("idle_states", [(3,), (3, 9)])
def test_full_32a_offer_survives_slow_ramp_and_idle_state_changes(idle_states):
    master, (active, idle) = setup_pair()
    with patch("TWCManager.TWCSlave.time.time") as clock:
        # Three minutes, including the former 10s cut-off and 60s retry boundaries.
        for seconds in range(0, 181, 2):
            clock.return_value = 1000 + seconds
            master.distributeEVSEPower()
            heartbeat(idle, idle_states[(seconds // 2) % len(idle_states)], 0)
            actual = min(32, 17.7 + seconds / 12)
            assert heartbeat(active, 1, actual) == 32
            assert master.num_cars_charging_now() == 1


@pytest.mark.parametrize("order", [(0, 1), (1, 0)])
def test_second_car_start_rebalances_from_actual_draw(order):
    master, (active, idle) = setup_pair()
    with patch("TWCManager.TWCSlave.time.time") as clock:
        clock.return_value = 1000
        master.distributeEVSEPower()
        heartbeat(active, 1, 32)
        heartbeat(idle, 3, 0)
        assert active.lastAmpsOffered == 32
        assert idle.lastAmpsOffered >= 6  # continuous readiness; no timed shutoff
        for step in range(10):
            clock.return_value = 1020 + step * 10
            for index in order:
                evse = (active, idle)[index]
                heartbeat(evse, 1, 16 if index == 0 else 6 + min(step * 2, 10))
            master.distributeEVSEPower()
        assert master.num_cars_charging_now() == 2
        assert active.lastAmpsOffered == idle.lastAmpsOffered == 16
        assert active.reportedAmpsActual + idle.reportedAmpsActual == 32


def test_five_second_session_end_debounce_restores_full_offer():
    master, (active, idle) = setup_pair()
    with patch("TWCManager.TWCSlave.time.time") as clock:
        clock.return_value = 1000
        master.distributeEVSEPower()
        heartbeat(active, 1, 16)
        heartbeat(idle, 1, 16)
        clock.return_value = 1010
        heartbeat(idle, 3, 0)
        assert master.num_cars_charging_now() == 2
        clock.return_value = 1016
        # Above the existing reactive-spike threshold; ramp remains slow.
        assert heartbeat(active, 1, 17.7) == 32
        assert master.num_cars_charging_now() == 1


def test_duplicate_api_view_of_gen2_still_uses_legacy_allocator():
    master, (active, idle) = setup_pair()
    api = SimpleNamespace(isLocal=False, isReadOnly=True)
    merged = MergedEVSE(master, idle, api)
    master.getDedupedEVSEs = lambda: [active, merged]
    master.distributeEVSEPower()
    assert active._evseTargetAmps is idle._evseTargetAmps is None


def test_mixed_controllable_api_vehicle_retains_central_distributor():
    master, (active, idle) = setup_pair()
    api = Mock()
    api.isReadOnly = False
    api.wantsToCharge = True
    api.maxPower = 32 * 240
    api.minPower = 6 * 240
    api.controllers = ["TeslaAPIController"]
    master.getDedupedEVSEs = lambda: [active, idle, api]
    master.distributeEVSEPower()
    assert active._evseTargetAmps is not None
    api.setTargetPower.assert_called_once()


@pytest.mark.parametrize(
    "flag,expected", [(None, 15), (False, 15), (True, 16), ("false", 15)]
)
def test_optional_headroom_rounding_through_real_heartbeats(flag, expected):
    master, (first, second) = setup_pair()
    if flag is not None:
        master.config["config"]["roundUpSharedCurrent"] = flag
    first.reportedAmpsActual = 16.42
    first.isCharging = True
    second.isCharging = True
    second.lastAmpsOffered = 14
    master.distributeEVSEPower()
    with patch("TWCManager.TWCSlave.time.time", return_value=1000):
        assert heartbeat(second, 1, 14.85) == expected


@pytest.mark.parametrize(
    "peer_draw,expected", [(16.01, 16), (16.42, 16), (16.99, 16), (17, 15), (17.2, 15)]
)
def test_rounding_tolerance_is_less_than_one_amp(peer_draw, expected):
    master, (first, second) = setup_pair()
    master.config["config"]["roundUpSharedCurrent"] = True
    first.reportedAmpsActual = peer_draw
    first.isCharging = second.isCharging = True
    second.lastAmpsOffered = 14
    master.distributeEVSEPower()
    with patch("TWCManager.TWCSlave.time.time", return_value=1000):
        offer = heartbeat(second, 1, 14)
    assert offer == expected
    assert peer_draw + offer < 33
    assert offer <= 16


def test_rounding_does_not_raise_policy_fair_share_or_per_charger_cap():
    master, (first, second) = setup_pair()
    master.config["config"]["roundUpSharedCurrent"] = True
    master.getMaxAmpsToDivideAmongSlaves = lambda: 30
    master.settings["spikeAmpsProactively"] = 0
    master.settings["spikeAmpsReactively"] = 0
    first.reportedAmpsActual = 15.42
    first.isCharging = second.isCharging = True
    second.lastAmpsOffered = 14
    master.distributeEVSEPower()
    with patch("TWCManager.TWCSlave.time.time", return_value=1000):
        assert heartbeat(second, 1, 14) == 15
    second.wiringMaxAmps = 12
    second.lastAmpsOffered = 10
    with patch("TWCManager.TWCSlave.time.time", return_value=1010):
        assert heartbeat(second, 1, 10) == 12


def test_enabled_flag_keeps_both_16a_offers_stable_with_fractional_reports():
    master, (first, second) = setup_pair()
    master.config["config"]["roundUpSharedCurrent"] = True
    first.reportedAmpsActual = 16.42
    second.reportedAmpsActual = 15.85
    first.isCharging = second.isCharging = True
    with patch("TWCManager.TWCSlave.time.time") as clock:
        for seconds in range(0, 181, 2):
            clock.return_value = 1000 + seconds
            master.distributeEVSEPower()
            assert heartbeat(first, 1, 16.42) == 16
            assert heartbeat(second, 1, 15.85) == 16


def test_rounding_does_not_apply_to_centralized_targets():
    master, (first, second) = setup_pair()
    master.config["config"]["roundUpSharedCurrent"] = True
    first.reportedAmpsActual = 16.42
    second._evseTargetAmps = 16
    second.lastAmpsOffered = 14
    assert second.set_last_amps_offered(16) == 15
