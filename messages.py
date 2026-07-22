import uuid
from typing import Any


def build_connection_response(opID: int, snscuuid_arr: list[int] | None = None) -> dict[str, object]:
    """Build BSSCI conRsp.

    Per BSSCI spec, the Service Center must provide its OWN session UUID
    (snScUuid). Echoing the base station's snBsUuid makes the BS believe the
    previous session is being resumed, so it expects SC opIds to continue
    strictly decrementing from the previous session (snScOpId). Since our
    per-connection opId counter restarts at -1, the BS then rejects the next
    SC-initiated operation (e.g. attPrp) as malformed and drops the link.

    We therefore always start a fresh session: snResume=False plus a new
    random 16-byte session UUID.
    """
    if snscuuid_arr is None:
        snscuuid_arr = list(uuid.uuid4().bytes)
    return {
        "command": "conRsp",
        "scEui": 8391082416558637055,
        "opId": opID,
        "snResume": False,
        "snScUuid": snscuuid_arr,
    }


def build_attach_request(sensor: dict[str, Any], opID: int) -> dict[str, object]:
    return {
        "command": "attPrp",
        "opId": opID,
        "epEui": int.from_bytes(bytes.fromhex(sensor["eui"]), "big"),
        "bidi": sensor["bidi"],
        "nwkSnKey": list(bytes.fromhex(sensor["nwKey"])),
        "shAddr": int.from_bytes(bytes.fromhex(sensor["shortAddr"]), "big"),
        "lastPacketCnt": 0,
        "dualChan": True,
        "repetition": False,
        "wideCarrOff": False,
        "longBlkDist": False,
    }


def build_attach_complete(opID: int) -> dict[str, object]:
    return {"command": "attPrpCmp", "opId": opID}


def build_detach_request(eui: str, opID: int) -> dict[str, object]:
    return {
        "command": "detPrp",  # BSSCI protocol: detach propagate
        "opId": opID,
        "epEui": int.from_bytes(bytes.fromhex(eui), "big"),
    }


def build_detach_complete(opID: int) -> dict[str, object]:
    return {"command": "detPrpCmp", "opId": opID}


def build_ping_response(opID: int) -> dict[str, object]:
    return {"command": "pingRsp", "opId": opID}


def build_status_request(opID: int) -> dict[str, object]:
    return {"command": "status", "opId": opID}


def build_status_complete(opID: int) -> dict[str, object]:
    return {"command": "statusCmp", "opId": opID}


def build_ul_response(opID: int) -> dict[str, object]:
    return {"command": "ulDataRsp", "opId": opID}


# Variable MAC (VM) Sub-Channel Messages
# Per ETSI TS 103357 - VM mode for metering devices with longer messages and acknowledgement


def build_vm_activate_request(opID: int, mac_type: int = 0) -> dict[str, object]:
    """Build VM sub-channel activate request

    Per BSSCI VM specification:
    - command: "vm.activate"
    - opId: Numeric ID of the operation
    - macType: Numeric MAC-Type of the intended Variable MAC
    """
    return {
        "command": "vm.activate",
        "opId": opID,
        "macType": mac_type,
    }


def build_vm_activate_response(opID: int) -> dict[str, object]:
    """Build VM sub-channel activate response

    Per BSSCI VM specification:
    - command: "vm.activateRsp"
    - opId: Numeric ID of the operation
    """
    return {
        "command": "vm.activateRsp",
        "opId": opID,
    }


def build_vm_deactivate_request(opID: int, mac_type: int = 0) -> dict[str, object]:
    """Build VM sub-channel deactivate request

    Per BSSCI VM specification:
    - command: "vm.deactivate"
    - opId: Numeric ID of the operation
    - macType: Numeric - MAC-Type of the intended Variable MAC
    """
    return {
        "command": "vm.deactivate",
        "opId": opID,
        "macType": mac_type,
    }


def build_vm_deactivate_response(opID: int) -> dict[str, object]:
    """Build VM sub-channel deactivate response

    Per BSSCI VM specification:
    - command: "vm.deactivateRsp"
    - opId: Numeric ID of the operation
    """
    return {
        "command": "vm.deactivateRsp",
        "opId": opID,
    }


def build_vm_status_request(opID: int) -> dict[str, object]:
    """Build VM sub-channel status request

    Per BSSCI VM specification:
    - command: "vm.status"
    - opId: Numeric ID of the operation

    Response will contain macTypes: Numeric[] - List of activated macTypes
    """
    return {
        "command": "vm.status",
        "opId": opID,
    }


def build_vm_status_response(opID: int, mac_types: list | None = None) -> dict[str, object]:
    """Build VM sub-channel status response

    Per BSSCI VM specification:
    - command: "vm.statusRsp"
    - opId: Numeric ID of the operation
    - macTypes: Numeric[] - List of activated macTypes
    """
    return {
        "command": "vm.statusRsp",
        "opId": opID,
        "macTypes": mac_types or [],
    }


def build_vm_dl_data(
    opID: int,
    mac_type: int,
    user_data: list,
    trx_time: int = 0,
    sys_time: int = 0,
    freq_off: int = 0,
    ul_snr: float = 0,
    ul_rssi: float = 0,
    carr_off_range: int = 5,
    carr_space: int = 1,
    ul_crc: list | None = None,
    tsi: int = 128,
    sync_burst: bool = False,
    dual_chan: bool = False,
    repetition: bool = False,
    long_blk_dist: bool = False,
) -> dict[str, object]:
    """Build VM downlink data message (Service Center -> Base Station -> Endpoint)

    Per BSSCI VM specification:
    - command: "vm.dlData"
    - opId: Numeric ID of the operation
    - macType: Numeric - MAC-Type of Variable MAC
    - userData: Numeric[n] - End Point user data U-MPDU
    - trxTime: Transceiver time of transmission (64 bit, ns resolution)
    - sysTime: Unix UTC time of transmission (64 bit, ns resolution)
    - freqOff: Frequency offset from center in Hz
    - ulSnr: Uplink reception SNR in dB
    - ulRssi: Uplink reception RSSI in dBm
    - carrOffRange: Carrier offset range (5 or 1)
    - carrSpace: Carrier spacing (0=narrow, 1=standard, 2=wide)
    - ulCrc: Uplink header and payload CRC [header_crc, payload_crc]
    - tsi: Transmission start time indicator (21-16383, default 128)
    - syncBurst: True to enable sync burst
    - dualChan: True to enable dual channel
    - repetition: True to enable core frame repetition
    - longBlkDist: True to enable long block distance
    """
    return {
        "command": "vm.dlData",
        "opId": opID,
        "macType": mac_type,
        "userData": user_data,
        "trxTime": trx_time,
        "sysTime": sys_time,
        "freqOff": freq_off,
        "ulSnr": ul_snr,
        "ulRssi": ul_rssi,
        "carrOffRange": carr_off_range,
        "carrSpace": carr_space,
        "ulCrc": ul_crc or [0, 0],
        "tsi": tsi,
        "syncBurst": sync_burst,
        "dualChan": dual_chan,
        "repetition": repetition,
        "longBlkDist": long_blk_dist,
    }


def build_vm_dl_data_response(opID: int) -> dict[str, object]:
    """Build VM downlink data response

    Per BSSCI VM specification:
    - command: "vm.dlDataRsp"
    - opId: Numeric ID of the operation
    """
    return {
        "command": "vm.dlDataRsp",
        "opId": opID,
    }


def build_vm_ul_data_response(opID: int) -> dict[str, object]:
    """Build VM uplink data response (acknowledge receipt of VM uplink data)

    Per BSSCI VM specification:
    - command: "vm.ulDataRsp"
    - opId: Numeric ID of the operation
    """
    return {
        "command": "vm.ulDataRsp",
        "opId": opID,
    }
