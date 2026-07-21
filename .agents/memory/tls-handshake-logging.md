---
name: TLS handshake debugging
description: Why failed base-station TLS handshakes produced zero logs, and the pattern that fixes it
---

Rule: never rely on `asyncio.start_server(..., ssl=ctx)` alone when connection diagnostics matter — accept plain TCP, log the peer, then `await writer.start_tls(ctx)` inside a try/except that logs SSLError / reset / timeout distinctly.

**Why:** asyncio's SSLProtocol swallows most server-side handshake failures (connection resets, missing client certs with early close) without ever calling the loop exception handler, so a base station that fails mTLS leaves no trace in logs. Verified by standalone repro on Python 3.12.

**How to apply:** BSSCI TLS server uses this wrapper pattern; failure paths must `writer.close(); await writer.wait_closed()`. Debug env toggles exist: `TLS_REQUIRE_CLIENT_CERT=false` (cert problem test) and `TLS_COMPAT_MODE=true` (SECLEVEL=1 for embedded TLS stacks). Defaults stay strict.
