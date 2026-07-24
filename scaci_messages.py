"""SCACI message builders.

SC-initiated operations use negative opIds (decrementing from -1).
AC-initiated operations use positive opIds (incrementing from 0).

Timestamps are 64-bit nanoseconds UTC (use scaci_protocol.ns_now()).
EUIs are integers at the wire boundary (use scaci_protocol.eui_to_int()).
"""

import uuid
from typing import Any

from scaci_protocol import ns_now

# ---------------------------------------------------------------------------
# Responses to AC-initiated operations
# ---------------------------------------------------------------------------


def build_con_response(op_id: int, sc_eui: int = 0) -> dict[str, Any]:
    """conRsp — SC responds to AC's con request.

    Always starts a fresh session (snResume=False, new random session UUID).
    """
    return {
        "command": "conRsp",
        "opId": op_id,
        "scEui": sc_eui,
        "snResume": False,
        "snScUuid": list(uuid.uuid4().bytes),
    }


def build_con_complete(op_id: int) -> dict[str, Any]:
    """conCmp — SC finalises the connection handshake."""
    return {"command": "conCmp", "opId": op_id}


def build_ping_response(op_id: int) -> dict[str, Any]:
    """pingRsp — SC responds to AC's ping."""
    return {"command": "pingRsp", "opId": op_id}


def build_ping_complete(op_id: int) -> dict[str, Any]:
    """pingCmp — SC completes the ping exchange."""
    return {"command": "pingCmp", "opId": op_id}


def build_reg_response(op_id: int, rc: int = 0) -> dict[str, Any]:
    """regRsp — SC acknowledges endpoint registration from AC."""
    return {"command": "regRsp", "opId": op_id, "rc": rc}


def build_reg_complete(op_id: int) -> dict[str, Any]:
    """regCmp — SC finalises endpoint registration."""
    return {"command": "regCmp", "opId": op_id}


def build_dereg_response(op_id: int, rc: int = 0) -> dict[str, Any]:
    """deregRsp — SC acknowledges endpoint deregistration from AC."""
    return {"command": "deregRsp", "opId": op_id, "rc": rc}


def build_dereg_complete(op_id: int) -> dict[str, Any]:
    """deregCmp — SC finalises endpoint deregistration."""
    return {"command": "deregCmp", "opId": op_id}


def build_dl_data_que_response(op_id: int, rc: int = 0) -> dict[str, Any]:
    """dlDataQueRsp — SC acknowledges downlink data queuing request."""
    return {"command": "dlDataQueRsp", "opId": op_id, "rc": rc}


def build_dl_data_que_complete(op_id: int) -> dict[str, Any]:
    """dlDataQueCmp — SC finalises downlink data queuing."""
    return {"command": "dlDataQueCmp", "opId": op_id}


def build_dl_data_rev_response(op_id: int, rc: int = 0) -> dict[str, Any]:
    """dlDataRevRsp — SC acknowledges downlink data revocation."""
    return {"command": "dlDataRevRsp", "opId": op_id, "rc": rc}


def build_dl_data_rev_complete(op_id: int) -> dict[str, Any]:
    """dlDataRevCmp — SC finalises downlink data revocation."""
    return {"command": "dlDataRevCmp", "opId": op_id}


def build_error_response(op_id: int, rc: int = 95) -> dict[str, Any]:
    """Generic error response (rc=95 = POSIX ENOTSUP — operation not supported)."""
    return {"command": "error", "opId": op_id, "rc": rc}


# ---------------------------------------------------------------------------
# SC-initiated operations (use negative opIds)
# ---------------------------------------------------------------------------


def build_status_request(op_id: int) -> dict[str, Any]:
    """status — SC queries AC for status information."""
    return {"command": "status", "opId": op_id}


def build_status_complete(op_id: int) -> dict[str, Any]:
    """statusCmp — SC completes the status exchange after receiving statusRsp."""
    return {"command": "statusCmp", "opId": op_id}


def build_ul_data(
    op_id: int,
    ep_eui: int,
    rx_time: int,
    data: list[int],
    snr: float = 0.0,
    rssi: float = 0.0,
    cnt: int = 0,
    bs_eui: int = 0,
    sh_addr: int = 0,
) -> dict[str, Any]:
    """ulData — SC forwards uplink sensor data to AC.

    rxTime is nanoseconds UTC (64-bit).  epEui and bsEui are integers.
    """
    return {
        "command": "ulData",
        "opId": op_id,
        "epEui": ep_eui,
        "bsEui": bs_eui,
        "rxTime": rx_time,
        "snr": snr,
        "rssi": rssi,
        "cnt": cnt,
        "shAddr": sh_addr,
        "data": data,
    }


def build_ul_data_complete(op_id: int) -> dict[str, Any]:
    """ulDataCmp — SC completes uplink data forwarding after receiving ulDataRsp."""
    return {"command": "ulDataCmp", "opId": op_id}


def build_ep_stat(
    op_id: int,
    ep_eui: int,
    online: bool,
    last_seen_ns: int | None = None,
) -> dict[str, Any]:
    """epStat — SC sends endpoint status to AC."""
    msg: dict[str, Any] = {
        "command": "epStat",
        "opId": op_id,
        "epEui": ep_eui,
        "online": online,
    }
    if last_seen_ns is not None:
        msg["lastSeen"] = last_seen_ns
    return msg


def build_ep_stat_complete(op_id: int) -> dict[str, Any]:
    """epStatCmp — SC completes the endpoint status exchange."""
    return {"command": "epStatCmp", "opId": op_id}


def build_tx_data_res(
    op_id: int,
    ep_eui: int,
    rc: int = 0,
    tx_time: int | None = None,
) -> dict[str, Any]:
    """dlDataRes (wire: txDataRes) — SC reports DL TX result to AC.

    Note: spec has a typo; the Rsp/Cmp commands are named txDataResRsp/txDataResCmp
    but the initiating command is dlDataRes.
    """
    msg: dict[str, Any] = {
        "command": "dlDataRes",
        "opId": op_id,
        "epEui": ep_eui,
        "rc": rc,
    }
    if tx_time is not None:
        msg["txTime"] = tx_time
    return msg


def build_tx_data_res_complete(op_id: int) -> dict[str, Any]:
    """txDataResCmp — SC completes DL TX result exchange."""
    return {"command": "txDataResCmp", "opId": op_id}
