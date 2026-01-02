from typing import Any


def build_connection_response(opID: int, snscuuid_arr: list[int]) -> dict[str, object]:
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
        "epEui": int.from_bytes(bytes.fromhex(eui), "big")
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

def build_vm_activate_request(sensor_eui: str, opID: int, vm_channel: int = 0) -> dict[str, object]:
    """Build VM sub-channel activate request"""
    return {
        "command": "vmActivate",
        "opId": opID,
        "epEui": int.from_bytes(bytes.fromhex(sensor_eui), "big"),
        "vmChan": vm_channel,  # VM channel number (0-3 typically)
    }


def build_vm_activate_response(opID: int, code: int = 0) -> dict[str, object]:
    """Build VM sub-channel activate response"""
    return {
        "command": "vmActRsp",
        "opId": opID,
        "code": code,  # 0 = success
    }


def build_vm_deactivate_request(sensor_eui: str, opID: int) -> dict[str, object]:
    """Build VM sub-channel deactivate request"""
    return {
        "command": "vmDeactivate",
        "opId": opID,
        "epEui": int.from_bytes(bytes.fromhex(sensor_eui), "big"),
    }


def build_vm_deactivate_response(opID: int, code: int = 0) -> dict[str, object]:
    """Build VM sub-channel deactivate response"""
    return {
        "command": "vmDeactRsp",
        "opId": opID,
        "code": code,
    }


def build_vm_status_request(sensor_eui: str, opID: int) -> dict[str, object]:
    """Build VM sub-channel status request"""
    return {
        "command": "vmStatus",
        "opId": opID,
        "epEui": int.from_bytes(bytes.fromhex(sensor_eui), "big"),
    }


def build_vm_status_response(opID: int, active: bool = False, vm_channel: int = 0) -> dict[str, object]:
    """Build VM sub-channel status response"""
    return {
        "command": "vmStatusRsp",
        "opId": opID,
        "active": active,
        "vmChan": vm_channel,
    }


def build_vm_dl_data(sensor_eui: str, opID: int, data: bytes, port: int = 1) -> dict[str, object]:
    """Build VM downlink data message (Service Center -> Base Station -> Endpoint)"""
    return {
        "command": "vmDlData",
        "opId": opID,
        "epEui": int.from_bytes(bytes.fromhex(sensor_eui), "big"),
        "port": port,
        "data": list(data),
    }


def build_vm_dl_data_response(opID: int, code: int = 0) -> dict[str, object]:
    """Build VM downlink data response"""
    return {
        "command": "vmDlDataRsp",
        "opId": opID,
        "code": code,
    }


def build_vm_ul_data_response(opID: int) -> dict[str, object]:
    """Build VM uplink data response (acknowledge receipt of VM uplink data)"""
    return {
        "command": "vmUlDataRsp",
        "opId": opID,
    }
