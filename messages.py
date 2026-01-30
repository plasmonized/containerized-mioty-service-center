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


def build_ul_complete(opID: int) -> dict[str, object]:
    return {"command": "ulDataCmp", "opId": opID}


def build_attach_response(opID: int, nwkSnKey: list, shAddr: int = None) -> dict[str, object]:
    """Build attach response for over-the-air attach initiated by base station
    
    Per BSSCI specification 5.6.2:
    - command: "attRsp"
    - opId: ID of the operation
    - nwkSnKey: 16 Byte End Point network session key
    - shAddr: End Point short address (only if not assigned by Base Station)
    """
    response = {
        "command": "attRsp",
        "opId": opID,
        "nwkSnKey": nwkSnKey,
    }
    if shAddr is not None:
        response["shAddr"] = shAddr
    return response


def build_detach_response(opID: int) -> dict[str, object]:
    """Build detach response for over-the-air detach initiated by base station
    
    Per BSSCI specification 5.7.2:
    - command: "detRsp"
    - opId: ID of the operation
    """
    return {"command": "detRsp", "opId": opID}


def build_dl_data_result_response(opID: int) -> dict[str, object]:
    """Build DL data result response
    
    Per BSSCI specification 5.14.2:
    - command: "dlDataResRsp"
    - opId: ID of the operation
    """
    return {"command": "dlDataResRsp", "opId": opID}


def build_dl_rx_status_response(opID: int) -> dict[str, object]:
    """Build DL RX status response
    
    Per BSSCI specification 5.15.2:
    - command: "dlRxStatRsp"
    - opId: ID of the operation
    """
    return {"command": "dlRxStatRsp", "opId": opID}


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


def build_vm_deactivate_request(opID: int) -> dict[str, object]:
    """Build VM sub-channel deactivate request
    
    Per BSSCI VM specification:
    - command: "vm.deactivate"
    - opId: Numeric ID of the operation
    """
    return {
        "command": "vm.deactivate",
        "opId": opID,
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


def build_vm_status_response(opID: int, mac_types: list = None) -> dict[str, object]:
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
