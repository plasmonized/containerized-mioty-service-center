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


_POSIX_NAMES: dict[int, str] = {
    0: "OK",
    1: "EPERM",
    2: "ENOENT",
    3: "ESRCH",
    12: "ENOMEM",
    13: "EACCES",
    16: "EBUSY",
    22: "EINVAL",
    28: "ENOSPC",
    95: "ENOTSUP",
}


def build_error_response(op_id: int, rc: int = 95, message: str = "") -> dict[str, Any]:
    """Generic error response with POSIX code and human-readable message.

    rc=95 = POSIX ENOTSUP — operation not supported (default for unsupported/unknown commands).
    """
    return {
        "command": "error",
        "opId": op_id,
        "rc": rc,
        "message": message or _POSIX_NAMES.get(rc, f"errno {rc}"),
    }


# ---------------------------------------------------------------------------
# SC-initiated operations (use negative opIds)
# ---------------------------------------------------------------------------


def build_status_response(op_id: int, sc_info: dict[str, Any]) -> dict[str, Any]:
    """statusRsp — SC replies to AC-initiated status query with SC health data.

    Fields per SCACI v1.0.0:
      rc=0 OK, message = human-readable status, timeNs = current UTC nanoseconds,
      uptimeS = SC uptime in seconds, bsConnected/epRegistered/epOnline = counters,
      basestations = per-BS detail objects.
    """
    return {
        "command": "statusRsp",
        "opId": op_id,
        "rc": sc_info.get("rc", 0),
        "message": sc_info.get("message", "OK"),
        "timeNs": sc_info.get("time_ns", ns_now()),
        "uptimeS": sc_info.get("uptime_s", 0),
        "bsConnected": sc_info.get("bs_connected", 0),
        "epRegistered": sc_info.get("ep_registered", 0),
        "epOnline": sc_info.get("ep_online", 0),
        "basestations": sc_info.get("basestations", []),
    }


def build_status_complete(op_id: int) -> dict[str, Any]:
    """statusCmp — SC completes the status exchange after sending statusRsp."""
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
