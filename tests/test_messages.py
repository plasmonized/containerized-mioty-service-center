"""Tests for the messages module — message builder functions.

These are pure functions: given the same input, they always return the
same dict. They are the easiest and most valuable things to test.
"""

from __future__ import annotations

from typing import Any

import pytest

from messages import (
    build_attach_complete,
    build_attach_request,
    build_connection_response,
    build_detach_complete,
    build_detach_request,
    build_ping_response,
    build_status_complete,
    build_status_request,
    build_ul_response,
    build_vm_activate_request,
    build_vm_activate_response,
    build_vm_deactivate_request,
    build_vm_deactivate_response,
    build_vm_dl_data,
    build_vm_dl_data_response,
    build_vm_status_request,
    build_vm_status_response,
    build_vm_ul_data_response,
)

# ── Constants ────────────────────────────────────────────────────────────────

SENSOR = {
    "eui": "A1B2C3D4E5F6",
    "bidi": True,
    "nwKey": "00" * 8,
    "shortAddr": "0001",
}


# ── Base Station Messages ────────────────────────────────────────────────────


class TestBuildConnectionResponse:
    """Tests for ``build_connection_response``."""

    def test_returns_dict_with_expected_keys(self) -> None:
        # Arrange
        op_id = 1
        uuid_arr = [100, 200, 300]

        # Act
        result = build_connection_response(op_id, uuid_arr)

        # Assert
        assert isinstance(result, dict)
        assert result["command"] == "conRsp"
        assert result["opId"] == op_id
        assert result["snScUuid"] == uuid_arr


    def test_forwards_empty_uuid_array(self) -> None:
        result = build_connection_response(0, [])
        assert result["snScUuid"] == []

    def test_generates_fresh_16_byte_uuid_when_not_given(self) -> None:
        result = build_connection_response(0)
        sn_uuid = result["snScUuid"]
        assert isinstance(sn_uuid, list)
        assert len(sn_uuid) == 16
        assert all(isinstance(b, int) and 0 <= b <= 255 for b in sn_uuid)
        # Two calls must produce different session UUIDs (new session each time)
        assert build_connection_response(0)["snScUuid"] != sn_uuid

    def test_never_resumes_session(self) -> None:
        assert build_connection_response(0)["snResume"] is False


class TestBuildAttachRequest:
    """Tests for ``build_attach_request``."""

    def test_returns_correct_structure(self) -> None:
        op_id = 42
        result = build_attach_request(SENSOR, op_id)

        assert result["command"] == "attPrp"
        assert result["opId"] == op_id
        assert "epEui" in result
        assert "nwkSnKey" in result
        assert "shAddr" in result

    def test_encodes_eui_as_big_endian_int(self) -> None:
        result = build_attach_request(SENSOR, 1)
        # "A1B2C3D4E5F6" → int.from_bytes(b"\xa1\xb2\xc3\xd4\xe5\xf6", "big")
        expected_eui = int.from_bytes(bytes.fromhex(SENSOR["eui"]), "big")
        assert result["epEui"] == expected_eui

    def test_bidi_is_forwarded(self) -> None:
        result = build_attach_request(SENSOR, 1)
        assert result["bidi"] is True

    def test_nwk_sn_key_is_raw_bytes(self) -> None:
        # Must be bytes so msgpack encodes it as bin type.
        # Miromico EdgeCard FW 5.1.0 rejects the array-of-ints form
        # with error 22 "attach propagate message malformed".
        result = build_attach_request(SENSOR, 1)
        expected_key = bytes.fromhex(SENSOR["nwKey"])
        assert result["nwkSnKey"] == expected_key
        assert isinstance(result["nwkSnKey"], bytes)


class TestBuildAttachComplete:
    def test_returns_correct_command(self) -> None:
        result = build_attach_complete(1)
        assert result == {"command": "attPrpCmp", "opId": 1}


class TestBuildDetachRequest:
    def test_returns_correct_structure(self) -> None:
        result = build_detach_request("A1B2C3D4E5F6", 5)
        assert result["command"] == "detPrp"
        assert result["opId"] == 5
        assert result["epEui"] == int.from_bytes(
            bytes.fromhex("A1B2C3D4E5F6"), "big"
        )


class TestBuildDetachComplete:
    def test_returns_correct_command(self) -> None:
        result = build_detach_complete(7)
        assert result == {"command": "detPrpCmp", "opId": 7}


class TestBuildPingResponse:
    def test_returns_correct_command(self) -> None:
        result = build_ping_response(3)
        assert result == {"command": "pingRsp", "opId": 3}


class TestBuildStatusRequest:
    def test_returns_correct_structure(self) -> None:
        result = build_status_request(99)
        assert result == {"command": "status", "opId": 99}


class TestBuildStatusComplete:
    def test_returns_correct_structure(self) -> None:
        result = build_status_complete(42)
        assert result == {"command": "statusCmp", "opId": 42}


class TestBuildUlResponse:
    def test_returns_correct_structure(self) -> None:
        result = build_ul_response(10)
        assert result == {"command": "ulDataRsp", "opId": 10}


# ── VM Sub-Channel Messages ──────────────────────────────────────────────────


class TestBuildVmActivateRequest:
    def test_default_mac_type_is_zero(self) -> None:
        result = build_vm_activate_request(1)
        assert result["macType"] == 0

    def test_custom_mac_type(self) -> None:
        result = build_vm_activate_request(1, mac_type=3)
        assert result["macType"] == 3


class TestBuildVmActivateResponse:
    def test_returns_correct_structure(self) -> None:
        result = build_vm_activate_response(1)
        assert result == {"command": "vm.activateRsp", "opId": 1}


class TestBuildVmDeactivateRequest:
    def test_default_mac_type_is_zero(self) -> None:
        result = build_vm_deactivate_request(1)
        assert result["macType"] == 0


class TestBuildVmDeactivateResponse:
    def test_returns_correct_structure(self) -> None:
        result = build_vm_deactivate_response(1)
        assert result == {"command": "vm.deactivateRsp", "opId": 1}


class TestBuildVmStatusRequest:
    def test_returns_correct_structure(self) -> None:
        result = build_vm_status_request(2)
        assert result == {"command": "vm.status", "opId": 2}


class TestBuildVmStatusResponse:
    def test_default_mac_types_is_empty_list(self) -> None:
        result = build_vm_status_response(1)
        assert result["macTypes"] == []

    def test_custom_mac_types(self) -> None:
        result = build_vm_status_response(1, mac_types=[1, 2, 3])
        assert result["macTypes"] == [1, 2, 3]


class TestBuildVmDlData:
    """Tests for build_vm_dl_data — the most complex message builder."""

    REQUIRED_KEYS = {
        "command", "opId", "macType", "userData", "trxTime", "sysTime",
        "freqOff", "ulSnr", "ulRssi", "carrOffRange", "carrSpace",
        "ulCrc", "tsi", "syncBurst", "dualChan", "repetition",
        "longBlkDist",
    }

    def test_all_required_keys_present(self) -> None:
        result = build_vm_dl_data(1, mac_type=2, user_data=[1, 2, 3])
        assert result.keys() == self.REQUIRED_KEYS

    def test_user_data_is_forwarded(self) -> None:
        user_data = [0x01, 0x02, 0x03]
        result = build_vm_dl_data(1, mac_type=2, user_data=user_data)
        assert result["userData"] == user_data

    def test_command_is_vm_dldata(self) -> None:
        result = build_vm_dl_data(1, mac_type=2, user_data=[1])
        assert result["command"] == "vm.dlData"

    @pytest.mark.parametrize("field", ["syncBurst", "dualChan", "repetition", "longBlkDist"])
    def test_boolean_flags_default_to_false(self, field: str) -> None:
        result = build_vm_dl_data(1, mac_type=2, user_data=[1])
        assert result[field] is False


class TestBuildVmDlDataResponse:
    def test_returns_correct_structure(self) -> None:
        result = build_vm_dl_data_response(5)
        assert result == {"command": "vm.dlDataRsp", "opId": 5}


class TestBuildVmUlDataResponse:
    def test_returns_correct_structure(self) -> None:
        result = build_vm_ul_data_response(8)
        assert result == {"command": "vm.ulDataRsp", "opId": 8}
