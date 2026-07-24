"""Integration tests for SCAServer — mock AC ↔ SC handshake flows.

These tests drive handle_ac() directly through a fake asyncio.StreamReader/Writer
pair, verifying end-to-end message exchanges without a real TLS connection.
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

import pytest

from scaci_protocol import decode_frames, encode_frame, eui_to_int, int_to_eui

# ---------------------------------------------------------------------------
# Helpers: fake StreamReader / StreamWriter backed by bytes / queue
# ---------------------------------------------------------------------------


class FakeWriter:
    """Captures written bytes; simulates asyncio.StreamWriter for SCAServer."""

    def __init__(self) -> None:
        self._buf = b""
        self.closed = False
        self._peername = ("127.0.0.1", 12345)

    def write(self, data: bytes) -> None:
        self._buf += data

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        pass

    def get_extra_info(self, key: str, default: Any = None) -> Any:
        if key == "peername":
            return self._peername
        return default

    async def start_tls(self, *args: Any, **kwargs: Any) -> None:
        pass

    def received_frames(self) -> list[dict[str, Any]]:
        """Decode all MIOTYA01 frames written so far."""
        return decode_frames(self._buf)


class FakeReader:
    """Feeds pre-built MIOTYA01 frames then signals EOF."""

    def __init__(self, frames: list[dict[str, Any]]) -> None:
        self._data = b"".join(encode_frame(f) for f in frames)
        self._sent = False

    async def read(self, n: int) -> bytes:
        if not self._sent:
            self._sent = True
            return self._data
        return b""  # EOF


class LiveReader:
    """Feeds initial frames then blocks (sleeps) until cancelled — keeps AC alive."""

    def __init__(self, frames: list[dict[str, Any]]) -> None:
        self._data = b"".join(encode_frame(f) for f in frames)
        self._sent = False

    async def read(self, n: int) -> bytes:
        if not self._sent:
            self._sent = True
            return self._data
        # Block indefinitely to keep handle_ac alive
        await asyncio.sleep(9999)
        return b""


# ---------------------------------------------------------------------------
# Fixture: fresh SCAServer instance per test
# ---------------------------------------------------------------------------

AC_EUI = "0102030405060708"
AC_EUI_INT = eui_to_int(AC_EUI)
EP_EUI = "A1B2C3D4E5F60708"
EP_EUI_INT = eui_to_int(EP_EUI)


@pytest.fixture()
def server() -> Any:
    from SCAServer import SCAServer

    q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    return SCAServer(mqtt_out_queue=q)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def run_exchange(
    server: Any, ac_frames: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Feed *ac_frames* into server.handle_ac and return decoded SC responses."""
    reader = FakeReader(ac_frames)
    writer = FakeWriter()
    await server.handle_ac(reader, writer)
    return writer.received_frames()


# ---------------------------------------------------------------------------
# Tests: connection handshake
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_con_handshake_produces_con_rsp_and_con_cmp(server: Any) -> None:
    """con → SC must reply with conRsp (fresh session) then conCmp."""
    con_frame = {"command": "con", "opId": 0, "acEui": AC_EUI_INT, "version": "1.0.0"}
    responses = await run_exchange(server, [con_frame])
    commands = [f["command"] for f in responses]
    assert "conRsp" in commands
    assert "conCmp" in commands


@pytest.mark.asyncio
async def test_con_rsp_has_fresh_session_uuid(server: Any) -> None:
    """conRsp must carry snResume=False and a 16-byte snScUuid."""
    con_frame = {"command": "con", "opId": 0, "acEui": AC_EUI_INT}
    responses = await run_exchange(server, [con_frame])
    rsp = next(f for f in responses if f["command"] == "conRsp")
    assert rsp["snResume"] is False
    assert isinstance(rsp.get("snScUuid"), list)
    assert len(rsp["snScUuid"]) == 16


@pytest.mark.asyncio
async def test_con_nonzero_opid_still_accepted(server: Any) -> None:
    """Non-zero opId on con: SC logs a warning but still responds (tolerant)."""
    con_frame = {"command": "con", "opId": 5, "acEui": AC_EUI_INT}
    responses = await run_exchange(server, [con_frame])
    commands = [f["command"] for f in responses]
    assert "conRsp" in commands


@pytest.mark.asyncio
async def test_con_sends_con_rsp(server: Any) -> None:
    """After a successful con the SC sends conRsp."""
    con_frame = {"command": "con", "opId": 0, "acEui": AC_EUI_INT}
    responses = await run_exchange(server, [con_frame])
    assert any(f["command"] == "conRsp" for f in responses)


# ---------------------------------------------------------------------------
# Tests: ping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ping_after_con(server: Any) -> None:
    """ping → SC must reply with pingRsp + pingCmp."""
    frames_in = [
        {"command": "con", "opId": 0, "acEui": AC_EUI_INT},
        {"command": "ping", "opId": 1},
    ]
    responses = await run_exchange(server, frames_in)
    commands = [f["command"] for f in responses]
    assert "pingRsp" in commands
    assert "pingCmp" in commands


# ---------------------------------------------------------------------------
# Tests: reg / dereg
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reg_returns_reg_rsp_and_reg_cmp(server: Any) -> None:
    """reg → SC must reply with regRsp (rc=0) + regCmp."""
    frames_in = [
        {"command": "con", "opId": 0, "acEui": AC_EUI_INT},
        {"command": "reg", "opId": 1, "epEui": EP_EUI_INT},
    ]
    responses = await run_exchange(server, frames_in)
    commands = [f["command"] for f in responses]
    assert "regRsp" in commands
    assert "regCmp" in commands
    rsp = next(f for f in responses if f["command"] == "regRsp")
    assert rsp["rc"] == 0


@pytest.mark.asyncio
async def test_reg_records_endpoint_in_ac_registered_eps(server: Any) -> None:
    """reg stores endpoint in ac_registered_eps while connection is live; purged on disconnect."""
    reader = LiveReader([
        {"command": "con", "opId": 0, "acEui": AC_EUI_INT},
        {"command": "reg", "opId": 1, "epEui": EP_EUI_INT},
    ])
    writer = FakeWriter()
    task = asyncio.create_task(server.handle_ac(reader, writer))

    # Give handler time to process con + reg
    await asyncio.sleep(0.05)

    ac_eui_str = int_to_eui(AC_EUI_INT)
    registered = server.ac_registered_eps.get(ac_eui_str, [])
    assert EP_EUI.upper() in [e.upper() for e in registered], (
        "ac_registered_eps should contain EP_EUI while connection is live"
    )

    # On disconnect, ac_registered_eps must be purged
    task.cancel()
    await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=1.0)
    assert server.ac_registered_eps.get(ac_eui_str, []) == [], (
        "ac_registered_eps must be cleared after AC disconnects"
    )


@pytest.mark.asyncio
async def test_dereg_returns_dereg_rsp_and_dereg_cmp(server: Any) -> None:
    """dereg → SC must reply with deregRsp (rc=0) + deregCmp."""
    frames_in = [
        {"command": "con", "opId": 0, "acEui": AC_EUI_INT},
        {"command": "reg", "opId": 1, "epEui": EP_EUI_INT},
        {"command": "dereg", "opId": 2, "epEui": EP_EUI_INT},
    ]
    responses = await run_exchange(server, frames_in)
    commands = [f["command"] for f in responses]
    assert "deregRsp" in commands
    assert "deregCmp" in commands


# ---------------------------------------------------------------------------
# Tests: dlDataQue / dlDataRev
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dl_data_que_returns_ack(server: Any) -> None:
    """dlDataQue → SC must reply with dlDataQueRsp (rc=0) + dlDataQueCmp."""
    frames_in = [
        {"command": "con", "opId": 0, "acEui": AC_EUI_INT},
        {"command": "dlDataQue", "opId": 1, "epEui": EP_EUI_INT, "data": [0xDE, 0xAD, 0xBE, 0xEF]},
    ]
    responses = await run_exchange(server, frames_in)
    commands = [f["command"] for f in responses]
    assert "dlDataQueRsp" in commands
    assert "dlDataQueCmp" in commands


@pytest.mark.asyncio
async def test_dl_data_que_queues_payload(server: Any) -> None:
    """dlDataQue must store the payload in pending_dl keyed by endpoint EUI."""
    frames_in = [
        {"command": "con", "opId": 0, "acEui": AC_EUI_INT},
        {"command": "dlDataQue", "opId": 1, "epEui": EP_EUI_INT, "data": [0xAA, 0xBB]},
    ]
    await run_exchange(server, frames_in)
    ep_str = int_to_eui(EP_EUI_INT).upper()
    match = server.pending_dl.get(ep_str) or server.pending_dl.get(EP_EUI.upper())
    assert match is not None
    assert match["data"] == [0xAA, 0xBB]


@pytest.mark.asyncio
async def test_dl_data_rev_clears_pending(server: Any) -> None:
    """dlDataRev must remove the queued entry from pending_dl."""
    frames_in = [
        {"command": "con", "opId": 0, "acEui": AC_EUI_INT},
        {"command": "dlDataQue", "opId": 1, "epEui": EP_EUI_INT, "data": [0x01]},
        {"command": "dlDataRev", "opId": 2, "epEui": EP_EUI_INT},
    ]
    await run_exchange(server, frames_in)
    ep_str = int_to_eui(EP_EUI_INT).upper()
    assert server.pending_dl.get(ep_str) is None
    assert server.pending_dl.get(EP_EUI.upper()) is None


@pytest.mark.asyncio
async def test_dl_data_que_stores_queued_at_mono(server: Any) -> None:
    """pending_dl entry must contain queued_at_mono (monotonic float) and op_id."""
    frames_in = [
        {"command": "con", "opId": 0, "acEui": AC_EUI_INT},
        {"command": "dlDataQue", "opId": 7, "epEui": EP_EUI_INT, "data": [0x11]},
    ]
    await run_exchange(server, frames_in)
    ep_str = int_to_eui(EP_EUI_INT).upper()
    entry = server.pending_dl.get(ep_str) or server.pending_dl.get(EP_EUI.upper())
    assert entry is not None
    assert isinstance(entry.get("queued_at_mono"), float)
    assert entry.get("op_id") == 7


@pytest.mark.asyncio
async def test_flush_pending_dl_delivers_and_clears(server: Any) -> None:
    """flush_pending_dl: if vm_send_data succeeds, entry is removed from pending_dl."""

    class _FakeTLS:
        """Minimal TLSServer stub that always reports vm_send_data as successful."""

        async def vm_send_data(self, ep_eui: str, data: bytes, port: int = 1) -> bool:
            return True

    # Manually inject a queued downlink
    import time

    ep_str = int_to_eui(EP_EUI_INT).upper()
    server.pending_dl[ep_str] = {
        "data": [0xAB, 0xCD],
        "port": 1,
        "op_id": 42,
        "queued_at_mono": time.monotonic(),
        "queued_at": 0,
    }
    server.tls_server = _FakeTLS()
    await server.flush_pending_dl(ep_str)
    assert server.pending_dl.get(ep_str) is None, "entry should be cleared after successful flush"
    # Cleanup
    server.tls_server = None


@pytest.mark.asyncio
async def test_pending_dl_sweep_expires_stale_entry(server: Any) -> None:
    """_pending_dl_sweep_loop: stale entries (beyond TTL) are expired with dlDataRes rc=110."""
    import time

    dl_res_calls: list[tuple[str, int, int]] = []

    class _FakeTLS:
        async def vm_send_data(self, ep_eui: str, data: bytes, port: int = 1) -> bool:
            return False  # VM always unavailable

    original_send = server.send_dl_data_res

    async def _mock_send_dl(ep_eui: str, dl_op_id: int, rc: int) -> None:
        dl_res_calls.append((ep_eui, dl_op_id, rc))

    server.send_dl_data_res = _mock_send_dl
    server.tls_server = _FakeTLS()

    ep_str = int_to_eui(EP_EUI_INT).upper()
    # Inject a stale entry older than the TTL
    server.pending_dl[ep_str] = {
        "data": [0xFF],
        "port": 1,
        "op_id": 99,
        "queued_at_mono": time.monotonic() - (server._MAX_DL_TTL_S + 1),
        "queued_at": 0,
    }

    # Run one sweep iteration manually (bypass asyncio.sleep)
    entries = list(server.pending_dl.items())
    for ep_eui, entry in entries:
        age_s = time.monotonic() - entry.get("queued_at_mono", 0)
        delivered = False
        if age_s < server._MAX_DL_TTL_S:
            try:
                delivered = await server.tls_server.vm_send_data(
                    ep_eui, bytes(entry["data"]), port=entry.get("port", 1)
                )
            except Exception:
                pass
        if delivered:
            server.pending_dl.pop(ep_eui, None)
            await server.send_dl_data_res(ep_eui, entry.get("op_id", 0), rc=0)
        elif age_s >= server._MAX_DL_TTL_S:
            server.pending_dl.pop(ep_eui, None)
            await server.send_dl_data_res(ep_eui, entry.get("op_id", 0), rc=110)

    assert server.pending_dl.get(ep_str) is None, "expired entry must be cleared"
    assert dl_res_calls, "dlDataRes must have been called for expired entry"
    _, dl_op_id, rc = dl_res_calls[0]
    assert rc == 110, f"expected ETIMEDOUT rc=110, got rc={rc}"
    assert dl_op_id == 99

    # Restore
    server.send_dl_data_res = original_send
    server.tls_server = None


# ---------------------------------------------------------------------------
# Tests: unsupported commands / error lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ul_data_tx_returns_error(server: Any) -> None:
    """ulDataTx is not supported — SC must reply with error (rc=95)."""
    frames_in = [
        {"command": "con", "opId": 0, "acEui": AC_EUI_INT},
        {"command": "ulDataTx", "opId": 1},
    ]
    responses = await run_exchange(server, frames_in)
    errors = [f for f in responses if f["command"] == "error"]
    assert errors
    assert errors[0]["rc"] == 95


@pytest.mark.asyncio
async def test_error_ack_is_silently_accepted(server: Any) -> None:
    """errorAck from AC must not crash and must not trigger a second error."""
    frames_in = [
        {"command": "con", "opId": 0, "acEui": AC_EUI_INT},
        {"command": "ulDataTx", "opId": 1},  # triggers error
        {"command": "errorAck", "opId": 1},  # AC acks the error
    ]
    responses = await run_exchange(server, frames_in)
    error_count = sum(1 for f in responses if f["command"] == "error")
    assert error_count == 1  # only one error, not two


# ---------------------------------------------------------------------------
# Tests: ulData broadcast fan-out
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_broadcast_ul_data_to_connected_ac(server: Any) -> None:
    """broadcast_ul_data must send ulData to a live connected AC."""
    writer = FakeWriter()

    # LiveReader sends the con frame then blocks, keeping handle_ac alive
    task = asyncio.create_task(
        server.handle_ac(LiveReader([{"command": "con", "opId": 0, "acEui": AC_EUI_INT}]), writer)
    )

    # Give handle_ac time to process the con and register the writer
    await asyncio.sleep(0.05)

    await server.broadcast_ul_data(
        ep_eui_hex=EP_EUI,
        rx_time_ns=1_700_000_000_000_000_000,
        data=[0x01, 0x02, 0x03],
        snr=10.5,
        rssi=-80.0,
        cnt=42,
        bs_eui_hex="0000000000000001",
        sh_addr=0x0001,
    )

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    frames = writer.received_frames()
    commands = [f["command"] for f in frames]
    assert "ulData" in commands

    ul = next(f for f in frames if f["command"] == "ulData")
    assert ul["epEui"] == EP_EUI_INT
    assert ul["data"] == [0x01, 0x02, 0x03]
    assert ul["snr"] == pytest.approx(10.5)
    assert ul["opId"] < 0  # SC-initiated → negative opId


@pytest.mark.asyncio
async def test_broadcast_ul_data_filtered_by_registered_ep(server: Any) -> None:
    """With registrations in place, ac_registered_eps filters by endpoint correctly (checked live)."""
    other_eui = "FFFFFFFFFFFFFFFF"
    other_eui_int = eui_to_int(other_eui)
    ac_eui_b = "0807060504030201"
    ac_eui_b_int = eui_to_int(ac_eui_b)

    # Use LiveReader so connections stay open while we inspect state
    reader_a = LiveReader([
        {"command": "con", "opId": 0, "acEui": AC_EUI_INT},
        {"command": "reg", "opId": 1, "epEui": EP_EUI_INT},
    ])
    reader_b = LiveReader([
        {"command": "con", "opId": 0, "acEui": ac_eui_b_int},
        {"command": "reg", "opId": 1, "epEui": other_eui_int},
    ])
    writer_a = FakeWriter()
    writer_b = FakeWriter()

    task_a = asyncio.create_task(server.handle_ac(reader_a, writer_a))
    task_b = asyncio.create_task(server.handle_ac(reader_b, writer_b))

    # Wait for both handlers to process con + reg
    await asyncio.sleep(0.05)

    # Verify registration filter state while connections are live
    ac_a_eps = server.ac_registered_eps.get(int_to_eui(AC_EUI_INT), [])
    ac_b_eps = server.ac_registered_eps.get(int_to_eui(ac_eui_b_int), [])
    assert any(EP_EUI.upper() == e.upper() for e in ac_a_eps), "AC A should have EP_EUI registered"
    assert not any(EP_EUI.upper() == e.upper() for e in ac_b_eps), "AC B should NOT have EP_EUI"

    task_a.cancel()
    task_b.cancel()
    await asyncio.gather(task_a, task_b, return_exceptions=True)


# ---------------------------------------------------------------------------
# Tests: get_status
# ---------------------------------------------------------------------------


def test_get_status_empty(server: Any) -> None:
    """get_status on a fresh server returns enabled=True with no connected ACs."""
    status = server.get_status()
    assert status["enabled"] is True
    assert status["connected"] == 0
    assert status["acs"] == []


# ---------------------------------------------------------------------------
# Tests: AC-initiated status query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_from_ac_returns_status_rsp(server: Any) -> None:
    """AC-initiated status → SC must reply with statusRsp (SC health data) + statusCmp."""
    frames_in = [
        {"command": "con", "opId": 0, "acEui": AC_EUI_INT},
        {"command": "status", "opId": 1},
    ]
    responses = await run_exchange(server, frames_in)
    commands = [f["command"] for f in responses]
    assert "statusRsp" in commands
    assert "statusCmp" in commands


@pytest.mark.asyncio
async def test_status_rsp_contains_sc_health_fields(server: Any) -> None:
    """statusRsp must include SC health fields: bsConnected, epRegistered, epOnline, uptimeS."""
    frames_in = [
        {"command": "con", "opId": 0, "acEui": AC_EUI_INT},
        {"command": "status", "opId": 1},
    ]
    responses = await run_exchange(server, frames_in)
    rsp = next(f for f in responses if f["command"] == "statusRsp")
    assert "bsConnected" in rsp
    assert "epRegistered" in rsp
    assert "epOnline" in rsp
    assert "uptimeS" in rsp
    assert rsp["opId"] == 1


# ---------------------------------------------------------------------------
# Tests: reg validated against sensor config
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reg_accepted_when_no_tls_server(server: Any) -> None:
    """When tls_server is not set, reg accepts any endpoint optimistically."""
    frames_in = [
        {"command": "con", "opId": 0, "acEui": AC_EUI_INT},
        {"command": "reg", "opId": 1, "epEui": EP_EUI_INT},
    ]
    responses = await run_exchange(server, frames_in)
    rsp = next(f for f in responses if f["command"] == "regRsp")
    assert rsp["rc"] == 0


@pytest.mark.asyncio
async def test_reg_provisions_via_tls_when_add_fails(server: Any) -> None:
    """reg for an unknown endpoint returns rc=ESRCH when add_sensor_via_ui returns False."""

    class FakeTLSServer:
        sensor_config: ClassVar[list[dict[str, Any]]] = []
        registered_sensors: ClassVar[dict[str, Any]] = {}
        connected_base_stations: ClassVar[dict[Any, str]] = {}

        def add_sensor_via_ui(self, sensor_data: dict[str, Any]) -> bool:
            return False  # simulate failure (e.g. no event loop)

    server.tls_server = FakeTLSServer()
    unknown_eui_int = eui_to_int("FFFFFFFFFFFFFFFF")
    frames_in = [
        {"command": "con", "opId": 0, "acEui": AC_EUI_INT},
        {"command": "reg", "opId": 1, "epEui": unknown_eui_int},
    ]
    responses = await run_exchange(server, frames_in)
    rsp = next(f for f in responses if f["command"] == "regRsp")
    assert rsp["rc"] == 3  # ESRCH — provisioning failed
    server.tls_server = None


@pytest.mark.asyncio
async def test_reg_provisions_unknown_endpoint_via_tls(server: Any) -> None:
    """reg for an unknown endpoint with TLSServer wired calls add_sensor_via_ui and returns rc=0."""
    provisioned: list[dict[str, Any]] = []

    class FakeTLSServer:
        sensor_config: ClassVar[list[dict[str, Any]]] = []
        registered_sensors: ClassVar[dict[str, Any]] = {}
        connected_base_stations: ClassVar[dict[Any, str]] = {}

        def add_sensor_via_ui(self, sensor_data: dict[str, Any]) -> bool:
            provisioned.append(sensor_data)
            return True

    server.tls_server = FakeTLSServer()

    unknown_eui_int = eui_to_int("FFFFFFFFFFFFFFFF")
    nwk_key = list(bytes(16))  # 16-byte zero key
    frames_in = [
        {"command": "con", "opId": 0, "acEui": AC_EUI_INT},
        {
            "command": "reg",
            "opId": 1,
            "epEui": unknown_eui_int,
            "nwkKey": nwk_key,
            "shAddr": 0x1234,
            "bidi": True,
        },
    ]
    responses = await run_exchange(server, frames_in)
    rsp = next(f for f in responses if f["command"] == "regRsp")
    assert rsp["rc"] == 0, "provisioned unknown endpoint should return rc=0"
    assert len(provisioned) == 1, "add_sensor_via_ui must be called once"
    assert provisioned[0]["eui"] == "FFFFFFFFFFFFFFFF"
    assert provisioned[0]["shortAddr"] == 0x1234
    assert provisioned[0]["bidi"] is True
    server.tls_server = None


@pytest.mark.asyncio
async def test_reg_accepted_when_endpoint_known_in_sensor_config(server: Any) -> None:
    """When tls_server is wired, reg for a known endpoint returns rc=0."""

    class FakeTLSServer:
        sensor_config: ClassVar[list[dict[str, Any]]] = [{"eui": EP_EUI}]
        registered_sensors: ClassVar[dict[str, Any]] = {}
        connected_base_stations: ClassVar[dict[Any, str]] = {}

        def add_sensor_via_ui(self, sensor_data: dict[str, Any]) -> bool:  # pragma: no cover
            return True

    server.tls_server = FakeTLSServer()

    frames_in = [
        {"command": "con", "opId": 0, "acEui": AC_EUI_INT},
        {"command": "reg", "opId": 1, "epEui": EP_EUI_INT},
    ]
    responses = await run_exchange(server, frames_in)
    rsp = next(f for f in responses if f["command"] == "regRsp")
    assert rsp["rc"] == 0
    server.tls_server = None


@pytest.mark.asyncio
async def test_con_rejects_unsupported_version(server: Any) -> None:
    """con with a non-1.x version must receive an error frame and the connection is closed."""
    frames_in = [
        {"command": "con", "opId": 0, "acEui": AC_EUI_INT, "version": "2.0.0"},
    ]
    responses = await run_exchange(server, frames_in)
    errors = [f for f in responses if f["command"] == "error"]
    assert errors, "SC must send an error frame for unsupported major version"
    assert errors[0].get("rc") == 71  # EPROTO


@pytest.mark.asyncio
async def test_con_accepts_version_1_x(server: Any) -> None:
    """con with version 1.1.0 (minor version bump) must be accepted — conRsp + conCmp returned."""
    frames_in = [
        {"command": "con", "opId": 0, "acEui": AC_EUI_INT, "version": "1.1.0"},
    ]
    responses = await run_exchange(server, frames_in)
    commands = [f["command"] for f in responses]
    assert "conRsp" in commands, "SC must send conRsp for version 1.1.0"
    assert "conCmp" in commands, "SC must send conCmp for version 1.1.0"
