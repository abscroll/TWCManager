"""Firmware requests must target real two-byte IDs without changing charge limits."""

import io
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from TWCManager.Control.HTTPControl import CreateHTTPHandlerClass
from TWCManager.Protocol.TWCProtocol import TWCProtocol


def make_master():
    master = Mock()
    master.TWCID = bytearray.fromhex("7777")
    # masterTWCID tracks an external master in slave mode; it is empty in
    # production master mode and must not be used as our sender address.
    master.masterTWCID = ""
    master.protocolVersion = 2
    master.getSlaveTWCs.return_value = [
        SimpleNamespace(TWCID=bytearray.fromhex(target))
        for target in ("3156", "5989")
    ]
    master.getModuleByName.side_effect = lambda name: (
        TWCProtocol(master) if name == "TWCProtocol" else master.interface
    )
    return master


@pytest.mark.parametrize("target", ["3156", "5989"])
@pytest.mark.parametrize("version,length", [(1, 13), (2, 15)])
def test_firmware_packet_bytes(target, version, length):
    master = make_master()
    master.protocolVersion = version
    message = TWCProtocol(master).createMessage(
        {"Command": "GetFirmwareVersion", "RecieverID": bytes.fromhex(target)}
    )
    assert len(message) == length
    assert message[:6] == bytes.fromhex("FB1B7777" + target)
    assert message[6:] == bytes(length - 6)


def test_firmware_default_uses_first_raw_id():
    message = TWCProtocol(make_master()).createMessage({"Command": "GetFirmwareVersion"})
    assert message[:6] == bytes.fromhex("FB1B77773156")


@pytest.mark.parametrize(
    "target,status",
    [
        ("3156", 204),
        ("5989", 204),
        ("1234", 404),
        ("315600", 400),
        ("zzzz", 400),
        (None, 400),
        (3156, 400),
    ],
)
def test_firmware_api_target_validation(target, status):
    master = make_master()
    handler_class = CreateHTTPHandlerClass(master)
    handler = object.__new__(handler_class)
    handler.url = SimpleNamespace(path="/api/sendDebugCommand")
    handler.post_data = json.dumps(
        {"commandName": "GetFirmwareVersion", "TWCID": target}
    ).encode()
    handler.wfile = io.BytesIO()
    handler.send_response = Mock()
    handler.end_headers = Mock()
    handler.debugLogAPI = Mock()
    handler.do_API_POST()
    handler.send_response.assert_called_once_with(status)
    if status == 204:
        sent = master.interface.send.call_args.args[0]
        assert sent[:6] == bytes.fromhex("FB1B7777" + target)
    else:
        master.interface.send.assert_not_called()


def test_firmware_api_no_chargers():
    master = make_master()
    master.getSlaveTWCs.return_value = []
    handler = object.__new__(CreateHTTPHandlerClass(master))
    handler.url = SimpleNamespace(path="/api/sendDebugCommand")
    handler.post_data = b'{"commandName":"GetFirmwareVersion"}'
    handler.wfile = io.BytesIO()
    handler.send_response = Mock()
    handler.end_headers = Mock()
    handler.debugLogAPI = Mock()
    handler.do_API_POST()
    handler.send_response.assert_called_once_with(409)
    master.interface.send.assert_not_called()


def test_firmware_uses_own_id_instead_of_external_master():
    master = make_master()
    master.masterTWCID = bytearray.fromhex("1234")
    message = TWCProtocol(master).createMessage({"Command": "GetFirmwareVersion"})
    assert message[2:4] == bytes.fromhex("7777")


@pytest.mark.parametrize("sender", [b"", b"A", b"ABCD"])
def test_firmware_rejects_invalid_sender(sender):
    master = make_master()
    master.TWCID = sender
    with pytest.raises(ValueError, match="exactly two bytes"):
        TWCProtocol(master).createMessage({"Command": "GetFirmwareVersion"})
