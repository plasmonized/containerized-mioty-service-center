"""SCAServer — SCACI (SC ↔ Application Center) TLS server.

Listens for incoming TLS connections from Application Centers (ACs),
implements the SCACI v1.0.0 protocol, and fans out uplink sensor data
received from base stations (via TLSServer) to all connected ACs.

Protocol framing: "MIOTYA01" identifier + 4-byte LE length + msgpack payload.
SC-initiated opIds: negative (decrementing from -1).
AC-initiated opIds: positive (incrementing from 0).
Timestamps: 64-bit nanoseconds UTC.
EUIs: integers at wire boundary.

Status direction: AC-initiated — AC sends 'status', SC replies with 'statusRsp'
containing SC health data (connected BSes, sensor counts, uptime).
"""

from __future__ import annotations

import asyncio
import logging
import ssl
import threading
import time
from datetime import UTC, datetime
from typing import Any

import bssci_config
import scaci_messages as msg
from observability import configure_logging
from scaci_protocol import decode_frames, encode_frame, eui_to_int, int_to_eui, ns_now

configure_logging(__name__)
logger = logging.getLogger(__name__)

_ENOTSUP = 95   # POSIX ENOTSUP — operation not supported
_ESRCH = 3      # POSIX ESRCH — endpoint not found in SC sensor config
_STARTED_AT = time.monotonic()


class SCAServer:
    """SCACI Application Center server.

    One instance is shared across all connections.  Per-AC state is tracked in
    dicts keyed by ``asyncio.StreamWriter``.

    Set ``sca_server.tls_server`` to the running TLSServer instance so that
    reg/dlDataQue can access live sensor state and send actual downlinks.
    """

    def __init__(
        self,
        mqtt_out_queue: asyncio.Queue[dict[str, Any]] | None,
    ) -> None:
        self.mqtt_out_queue = mqtt_out_queue

        # Optional reference to TLSServer — set by main.py after both are created.
        # Used to validate sensor registrations and to trigger actual downlinks.
        self.tls_server: Any = None

        # Per-connection op-id counters (SC uses negative ids, decrementing)
        self._ac_op_ids: dict[asyncio.streams.StreamWriter, int] = {}

        # writer → AC EUI string (set after successful con)
        self.connected_acs: dict[asyncio.streams.StreamWriter, str] = {}

        # writer → AC metadata dict (version, connected_at, …)
        self.ac_info: dict[asyncio.streams.StreamWriter, dict[str, Any]] = {}

        # AC EUI → list of registered endpoint EUIs
        self.ac_registered_eps: dict[str, list[str]] = {}

        # Pending SC-initiated operations: opId → {ac_writer, command, sent_at}
        self._pending_ops: dict[int, dict[str, Any]] = {}

        # Pending downlink queue requests from ACs: ep_eui → {payload, queued_at}
        # Used as fallback when the sensor has no active VM sub-channel.
        self.pending_dl: dict[str, dict[str, Any]] = {}

        self._state_lock = threading.RLock()
        self._background_tasks: set[asyncio.Task[Any]] = set()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _next_op_id(self, writer: asyncio.streams.StreamWriter) -> int:
        """Return the next SC-initiated op-id (negative, decrementing) for *writer*."""
        op_id = self._ac_op_ids.get(writer, -1)
        self._ac_op_ids[writer] = op_id - 1
        return op_id

    def _spawn(self, coro: Any) -> asyncio.Task[Any]:
        task: asyncio.Task[Any] = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    async def _send(self, writer: asyncio.streams.StreamWriter, data: dict[str, Any]) -> None:
        try:
            writer.write(encode_frame(data))
            await writer.drain()
        except Exception as exc:
            logger.warning("SCACI send error to %s: %s", self._ac_label(writer), exc)

    def _ac_label(self, writer: asyncio.streams.StreamWriter) -> str:
        eui = self.connected_acs.get(writer)
        if eui:
            return eui
        try:
            peer = writer.get_extra_info("peername")
            return str(peer)
        except Exception:
            return "unknown"

    async def _close(self, writer: asyncio.streams.StreamWriter) -> None:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass

    def _cleanup(self, writer: asyncio.streams.StreamWriter) -> None:
        with self._state_lock:
            ac_eui = self.connected_acs.pop(writer, None)
            self.ac_info.pop(writer, None)
            self._ac_op_ids.pop(writer, None)
            stale = [k for k, v in self._pending_ops.items() if v.get("writer") is writer]
            for k in stale:
                self._pending_ops.pop(k, None)
            if ac_eui:
                self.ac_registered_eps.pop(ac_eui, None)
        if ac_eui:
            logger.info("SCACI AC disconnected: %s", ac_eui)

    def _sc_health(self) -> dict[str, Any]:
        """Gather SC health info for statusRsp (best-effort, never raises)."""
        tls = self.tls_server
        try:
            bs_connected = len(tls.connected_base_stations) if tls else 0
        except Exception:
            bs_connected = 0
        try:
            ep_registered = len([
                v for v in tls.registered_sensors.values()
                if v.get("registered") and not str(v).endswith("_failure")
            ]) if tls else 0
        except Exception:
            ep_registered = 0
        try:
            ep_online = tls.get_sensor_online_count() if tls else 0
        except Exception:
            ep_online = 0
        uptime_s = int(time.monotonic() - _STARTED_AT)
        return {
            "bs_connected": bs_connected,
            "ep_registered": ep_registered,
            "ep_online": ep_online,
            "uptime_s": uptime_s,
        }

    def _is_known_endpoint(self, ep_eui: str) -> bool:
        """Return True if *ep_eui* is present in TLSServer's sensor_config."""
        tls = self.tls_server
        if tls is None:
            return True  # no validation possible — accept optimistically
        try:
            cfg: list[dict[str, Any]] = getattr(tls, "sensor_config", [])
            return any(s.get("eui", "").upper() == ep_eui.upper() for s in cfg)
        except Exception:
            return True

    # ------------------------------------------------------------------
    # Server startup
    # ------------------------------------------------------------------

    async def start_server(self) -> None:
        host = getattr(bssci_config, "SCACI_HOST", "0.0.0.0")
        port = getattr(bssci_config, "SCACI_PORT", 16019)
        cert = getattr(bssci_config, "SCACI_CERT_FILE", bssci_config.CERT_FILE)
        key = getattr(bssci_config, "SCACI_KEY_FILE", bssci_config.KEY_FILE)
        ca = getattr(bssci_config, "SCACI_CA_FILE", bssci_config.CA_FILE)
        require_cert = getattr(bssci_config, "SCACI_REQUIRE_CLIENT_CERT", True)

        logger.info("Setting up SCACI TLS context (cert=%s, ca=%s)", cert, ca)
        try:
            ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            ssl_ctx.load_cert_chain(certfile=cert, keyfile=key)
            ssl_ctx.load_verify_locations(cafile=ca)
            ssl_ctx.verify_mode = ssl.CERT_REQUIRED if require_cert else ssl.CERT_OPTIONAL
            compat_mode = getattr(bssci_config, "TLS_COMPAT_MODE", False)
            if compat_mode:
                ssl_ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
                ssl_ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        except FileNotFoundError as exc:
            logger.error("SCACI cert file not found: %s — server not started", exc)
            return
        except ssl.SSLError as exc:
            logger.error("SCACI SSL config error: %s — server not started", exc)
            return

        async def _handler(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            peer = writer.get_extra_info("peername")
            logger.info("SCACI incoming TCP from %s — starting TLS handshake", peer)
            try:
                await writer.start_tls(ssl_ctx, ssl_handshake_timeout=15.0)
            except (
                TimeoutError,
                ssl.SSLError,
                ConnectionResetError,
                BrokenPipeError,
                EOFError,
            ) as exc:
                logger.error("SCACI TLS handshake failed from %s: %s", peer, exc)
                await self._close(writer)
                return
            except Exception as exc:
                logger.error("SCACI TLS handshake error from %s: %s", peer, exc)
                await self._close(writer)
                return
            logger.info("SCACI TLS handshake OK from %s", peer)
            await self.handle_ac(reader, writer)

        server = await asyncio.start_server(_handler, host, port)
        logger.info("SCACI server listening on %s:%s", host, port)

        async with server:
            await server.serve_forever()

    # ------------------------------------------------------------------
    # Per-AC connection handler
    # ------------------------------------------------------------------

    async def handle_ac(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        buf = b""
        try:
            while True:
                chunk = await reader.read(65536)
                if not chunk:
                    logger.info("SCACI AC %s closed connection", self._ac_label(writer))
                    break
                buf += chunk
                frames = decode_frames(buf)
                buf = self._remaining_buf(buf, frames)
                for frame in frames:
                    await self._dispatch(writer, frame)
        except asyncio.CancelledError:
            pass
        except (ConnectionResetError, BrokenPipeError, EOFError):
            logger.info("SCACI AC %s connection lost", self._ac_label(writer))
        except Exception as exc:
            logger.error("SCACI AC %s handler error: %s", self._ac_label(writer), exc)
        finally:
            self._cleanup(writer)
            await self._close(writer)

    def _remaining_buf(self, buf: bytes, decoded_frames: list[dict[str, Any]]) -> bytes:
        """Return the unconsumed tail of *buf* after *decoded_frames* were parsed."""
        remaining = buf
        for _ in decoded_frames:
            if len(remaining) < 12:
                break
            length = int.from_bytes(remaining[8:12], byteorder="little")
            remaining = remaining[12 + length :]
        return remaining

    # ------------------------------------------------------------------
    # Message dispatcher
    # ------------------------------------------------------------------

    async def _dispatch(
        self, writer: asyncio.streams.StreamWriter, frame: dict[str, Any]
    ) -> None:
        command = frame.get("command", "")
        op_id = frame.get("opId", 0)
        ac_label = self._ac_label(writer)
        logger.debug("SCACI ← %s  cmd=%s opId=%s", ac_label, command, op_id)

        if command == "con":
            await self._handle_con(writer, frame)
        elif command == "conCmp":
            logger.debug("SCACI conCmp from %s opId=%s", ac_label, op_id)
        elif command == "ping":
            await self._handle_ping(writer, frame)
        elif command == "pingCmp":
            logger.debug("SCACI pingCmp from %s", ac_label)
        elif command == "status":
            # AC-initiated: AC queries SC for health information
            await self._handle_status(writer, frame)
        elif command == "statusCmp":
            logger.debug("SCACI statusCmp from %s opId=%s", ac_label, op_id)
        elif command == "reg":
            await self._handle_reg(writer, frame)
        elif command == "regCmp":
            logger.debug("SCACI regCmp from %s opId=%s", ac_label, op_id)
        elif command == "dereg":
            await self._handle_dereg(writer, frame)
        elif command == "deregCmp":
            logger.debug("SCACI deregCmp from %s opId=%s", ac_label, op_id)
        elif command == "dlDataQue":
            await self._handle_dl_data_que(writer, frame)
        elif command == "dlDataQueCmp":
            logger.debug("SCACI dlDataQueCmp from %s opId=%s", ac_label, op_id)
        elif command == "dlDataRev":
            await self._handle_dl_data_rev(writer, frame)
        elif command == "dlDataRevCmp":
            logger.debug("SCACI dlDataRevCmp from %s opId=%s", ac_label, op_id)
        elif command == "ulDataRsp":
            await self._handle_ul_data_rsp(writer, frame)
        elif command == "epStatRsp":
            await self._handle_ep_stat_rsp(writer, frame)
        elif command == "errorAck":
            # AC acknowledges an error response we sent — no further action needed
            logger.debug("SCACI errorAck from %s opId=%s", ac_label, op_id)
        elif command == "txDataResRsp":
            # AC acknowledges our dlDataRes notification
            await self._send(writer, msg.build_tx_data_res_complete(op_id))
        elif command == "txDataResCmp":
            logger.debug("SCACI txDataResCmp from %s opId=%s", ac_label, op_id)
        elif command in ("ulDataTx",) or command.startswith("rc."):
            logger.warning("SCACI unsupported command %s from %s", command, ac_label)
            await self._send(writer, msg.build_error_response(op_id, _ENOTSUP))
        else:
            logger.warning("SCACI unknown command %s from %s", command, ac_label)
            await self._send(writer, msg.build_error_response(op_id, _ENOTSUP))

    # ------------------------------------------------------------------
    # AC-initiated handlers
    # ------------------------------------------------------------------

    async def _handle_con(
        self, writer: asyncio.streams.StreamWriter, frame: dict[str, Any]
    ) -> None:
        op_id = frame.get("opId", 0)
        if op_id != 0:
            logger.warning(
                "SCACI con from %s has opId=%s (expected 0 per spec)",
                self._ac_label(writer),
                op_id,
            )
        ac_eui_int = frame.get("acEui", frame.get("bsEui", 0))
        ac_eui = int_to_eui(ac_eui_int) if ac_eui_int else "UNKNOWN"
        version = frame.get("version", frame.get("protVer", "1.0.0"))

        logger.info("SCACI con from AC %s (version=%s)", ac_eui, version)

        with self._state_lock:
            self.connected_acs[writer] = ac_eui
            self.ac_info[writer] = {
                "eui": ac_eui,
                "version": version,
                "connected_at": datetime.now(UTC).isoformat(),
                "peer": str(writer.get_extra_info("peername")),
            }

        await self._send(writer, msg.build_con_response(op_id))
        await self._send(writer, msg.build_con_complete(op_id))

    async def _handle_ping(
        self, writer: asyncio.streams.StreamWriter, frame: dict[str, Any]
    ) -> None:
        op_id = frame.get("opId", 0)
        await self._send(writer, msg.build_ping_response(op_id))
        await self._send(writer, msg.build_ping_complete(op_id))

    async def _handle_status(
        self, writer: asyncio.streams.StreamWriter, frame: dict[str, Any]
    ) -> None:
        """Handle AC-initiated status query — reply with SC health data."""
        op_id = frame.get("opId", 0)
        health = self._sc_health()
        logger.debug(
            "SCACI status from %s → SC health: %s", self._ac_label(writer), health
        )
        await self._send(writer, msg.build_status_response(op_id, health))
        await self._send(writer, msg.build_status_complete(op_id))

    async def _handle_reg(
        self, writer: asyncio.streams.StreamWriter, frame: dict[str, Any]
    ) -> None:
        op_id = frame.get("opId", 0)
        ep_eui_int = frame.get("epEui", 0)
        ep_eui = int_to_eui(ep_eui_int) if ep_eui_int else "UNKNOWN"
        ac_eui = self.connected_acs.get(writer, "UNKNOWN")

        logger.info("SCACI reg: AC %s registers endpoint %s", ac_eui, ep_eui)

        if not self._is_known_endpoint(ep_eui):
            logger.warning(
                "SCACI reg: endpoint %s not found in sensor config — rejecting (rc=%d)",
                ep_eui,
                _ESRCH,
            )
            await self._send(writer, msg.build_reg_response(op_id, rc=_ESRCH))
            await self._send(writer, msg.build_reg_complete(op_id))
            return

        with self._state_lock:
            eps = self.ac_registered_eps.setdefault(ac_eui, [])
            if ep_eui not in eps:
                eps.append(ep_eui)

        # If the endpoint is not yet attached to any BS, trigger an attach attempt.
        tls = self.tls_server
        if tls is not None:
            eui_key = ep_eui.upper()
            already_registered = tls.registered_sensors.get(eui_key, {}).get("registered", False)
            if not already_registered:
                sensor_cfg = next(
                    (s for s in tls.sensor_config if s.get("eui", "").upper() == eui_key),
                    None,
                )
                if sensor_cfg:
                    for writer_bs in list(tls.connected_base_stations.keys()):
                        try:
                            await tls.send_attach_request(writer_bs, sensor_cfg)
                        except Exception as exc:
                            logger.warning(
                                "SCACI reg: attach attempt failed for %s on BS: %s", ep_eui, exc
                            )

        await self._send(writer, msg.build_reg_response(op_id, rc=0))
        await self._send(writer, msg.build_reg_complete(op_id))

    async def _handle_dereg(
        self, writer: asyncio.streams.StreamWriter, frame: dict[str, Any]
    ) -> None:
        op_id = frame.get("opId", 0)
        ep_eui_int = frame.get("epEui", 0)
        ep_eui = int_to_eui(ep_eui_int) if ep_eui_int else "UNKNOWN"
        ac_eui = self.connected_acs.get(writer, "UNKNOWN")

        logger.info("SCACI dereg: AC %s deregisters endpoint %s", ac_eui, ep_eui)

        with self._state_lock:
            eps = self.ac_registered_eps.get(ac_eui, [])
            if ep_eui in eps:
                eps.remove(ep_eui)

        await self._send(writer, msg.build_dereg_response(op_id, rc=0))
        await self._send(writer, msg.build_dereg_complete(op_id))

    async def _handle_dl_data_que(
        self, writer: asyncio.streams.StreamWriter, frame: dict[str, Any]
    ) -> None:
        op_id = frame.get("opId", 0)
        ep_eui_int = frame.get("epEui", 0)
        ep_eui = int_to_eui(ep_eui_int) if ep_eui_int else "UNKNOWN"
        user_data: list[int] = frame.get("data", frame.get("userData", []))
        port: int = frame.get("port", 1)

        logger.info(
            "SCACI dlDataQue: downlink for endpoint %s (%d bytes, port=%d)",
            ep_eui,
            len(user_data),
            port,
        )

        # Attempt immediate delivery via VM sub-channel if tls_server is wired up.
        tls = self.tls_server
        dl_sent = False
        if tls is not None:
            try:
                dl_sent = await tls.vm_send_data(ep_eui, bytes(user_data), port=port)
                if dl_sent:
                    logger.info(
                        "SCACI dlDataQue: downlink dispatched via VM sub-channel for %s", ep_eui
                    )
            except Exception as exc:
                logger.warning(
                    "SCACI dlDataQue: vm_send_data failed for %s: %s — queuing instead", ep_eui, exc
                )

        if not dl_sent:
            # No VM active or tls_server unavailable — queue for later delivery
            with self._state_lock:
                self.pending_dl[ep_eui] = {
                    "data": user_data,
                    "port": port,
                    "queued_at": ns_now(),
                    "frame": frame,
                }
            logger.debug("SCACI dlDataQue: downlink queued for %s (VM not active)", ep_eui)

        await self._send(writer, msg.build_dl_data_que_response(op_id, rc=0))
        await self._send(writer, msg.build_dl_data_que_complete(op_id))

    async def _handle_dl_data_rev(
        self, writer: asyncio.streams.StreamWriter, frame: dict[str, Any]
    ) -> None:
        op_id = frame.get("opId", 0)
        ep_eui_int = frame.get("epEui", 0)
        ep_eui = int_to_eui(ep_eui_int) if ep_eui_int else "UNKNOWN"

        logger.info("SCACI dlDataRev: revoke downlink for endpoint %s", ep_eui)

        with self._state_lock:
            self.pending_dl.pop(ep_eui, None)

        await self._send(writer, msg.build_dl_data_rev_response(op_id, rc=0))
        await self._send(writer, msg.build_dl_data_rev_complete(op_id))

    # ------------------------------------------------------------------
    # Handlers for responses to SC-initiated operations
    # ------------------------------------------------------------------

    async def _handle_ul_data_rsp(
        self, writer: asyncio.streams.StreamWriter, frame: dict[str, Any]
    ) -> None:
        op_id = frame.get("opId", 0)
        with self._state_lock:
            self._pending_ops.pop(op_id, None)
        await self._send(writer, msg.build_ul_data_complete(op_id))

    async def _handle_ep_stat_rsp(
        self, writer: asyncio.streams.StreamWriter, frame: dict[str, Any]
    ) -> None:
        op_id = frame.get("opId", 0)
        with self._state_lock:
            self._pending_ops.pop(op_id, None)
        await self._send(writer, msg.build_ep_stat_complete(op_id))

    # ------------------------------------------------------------------
    # SC-initiated: ulData fan-out
    # ------------------------------------------------------------------

    async def broadcast_ul_data(
        self,
        ep_eui_hex: str,
        rx_time_ns: int,
        data: list[int],
        snr: float = 0.0,
        rssi: float = 0.0,
        cnt: int = 0,
        bs_eui_hex: str = "0000000000000000",
        sh_addr: int = 0,
    ) -> None:
        """Fan-out an uplink sensor packet to all connected Application Centers.

        Called by TLSServer after deduplication.
        Only ACs that have registered this endpoint receive the data.
        If no AC has registered anything, the packet is broadcast to all (open mode).
        """
        ep_eui_int = eui_to_int(ep_eui_hex) if len(ep_eui_hex) == 16 else 0
        bs_eui_int = eui_to_int(bs_eui_hex) if len(bs_eui_hex) == 16 else 0

        with self._state_lock:
            writers = list(self.connected_acs.keys())

        if not writers:
            return

        # Filter to ACs that registered this endpoint; open-broadcast if no registrations exist.
        with self._state_lock:
            any_registrations = any(self.ac_registered_eps.values())
            if any_registrations:
                writers = [
                    w
                    for w in writers
                    if ep_eui_hex.upper()
                    in [
                        e.upper()
                        for e in self.ac_registered_eps.get(self.connected_acs.get(w, ""), [])
                    ]
                ]

        for writer in writers:
            op_id = self._next_op_id(writer)
            ul_msg = msg.build_ul_data(
                op_id=op_id,
                ep_eui=ep_eui_int,
                rx_time=rx_time_ns,
                data=data,
                snr=snr,
                rssi=rssi,
                cnt=cnt,
                bs_eui=bs_eui_int,
                sh_addr=sh_addr,
            )
            with self._state_lock:
                self._pending_ops[op_id] = {
                    "writer": writer,
                    "command": "ulData",
                    "sent_at": time.monotonic(),
                }
            await self._send(writer, ul_msg)

    async def send_dl_data_res(
        self,
        ep_eui_hex: str,
        dl_op_id: int,
        rc: int,
    ) -> None:
        """Notify all ACs that registered this endpoint about a DL TX result (dlDataRes)."""
        ep_eui_int = eui_to_int(ep_eui_hex) if len(ep_eui_hex) == 16 else 0

        with self._state_lock:
            writers = list(self.connected_acs.keys())
            any_registrations = any(self.ac_registered_eps.values())
            if any_registrations:
                writers = [
                    w
                    for w in writers
                    if ep_eui_hex.upper()
                    in [
                        e.upper()
                        for e in self.ac_registered_eps.get(self.connected_acs.get(w, ""), [])
                    ]
                ]

        for writer in writers:
            op_id = self._next_op_id(writer)
            dl_res_msg = msg.build_tx_data_res(
                op_id=op_id,
                ep_eui=ep_eui_int,
                rc=rc,
            )
            with self._state_lock:
                self._pending_ops[op_id] = {
                    "writer": writer,
                    "command": "dlDataRes",
                    "sent_at": time.monotonic(),
                }
            await self._send(writer, dl_res_msg)
            logger.debug(
                "SCACI dlDataRes sent to AC for endpoint %s dl_op_id=%s rc=%s",
                ep_eui_hex,
                dl_op_id,
                rc,
            )

    async def send_ep_stat(
        self,
        ep_eui_hex: str,
        online: bool,
        last_seen_ns: int | None = None,
    ) -> None:
        """Send endpoint status update to all connected ACs."""
        ep_eui_int = eui_to_int(ep_eui_hex) if len(ep_eui_hex) == 16 else 0

        with self._state_lock:
            writers = list(self.connected_acs.keys())

        for writer in writers:
            op_id = self._next_op_id(writer)
            ep_msg = msg.build_ep_stat(
                op_id=op_id,
                ep_eui=ep_eui_int,
                online=online,
                last_seen_ns=last_seen_ns,
            )
            with self._state_lock:
                self._pending_ops[op_id] = {
                    "writer": writer,
                    "command": "epStat",
                    "sent_at": time.monotonic(),
                }
            await self._send(writer, ep_msg)

    # ------------------------------------------------------------------
    # Status introspection (for web UI)
    # ------------------------------------------------------------------

    def get_status(self) -> dict[str, Any]:
        """Return a snapshot of current AC connections for the web UI."""
        with self._state_lock:
            acs = []
            for writer, eui in self.connected_acs.items():
                info = self.ac_info.get(writer, {})
                acs.append(
                    {
                        "eui": eui,
                        "version": info.get("version", "?"),
                        "connected_at": info.get("connected_at", ""),
                        "peer": info.get("peer", ""),
                        "registered_eps": self.ac_registered_eps.get(eui, []),
                    }
                )
            return {
                "enabled": True,
                "connected": len(acs),
                "acs": acs,
            }
