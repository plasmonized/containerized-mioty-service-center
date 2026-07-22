---
name: BSSCI session resume vs opId continuity
description: Why echoing snBsUuid in conRsp breaks attach on strict base stations (Miromico error 22)
---

# Never echo the BS session UUID back as snScUuid

**Rule:** In the BSSCI `conRsp`, the Service Center must send its OWN session UUID (fresh random 16 bytes per connection, `snResume: false`). Never echo the base station's `snBsUuid`.

**Why:** Strict firmwares (Miromico EdgeCard swVersion 5.1.0, BSSCI 1.1.0) treat a matching session UUID as a session resume and expect SC-initiated opIds to continue strictly decrementing from the previous session's `snScOpId` (reported in the `con` message, e.g. -2). If the SC restarts its counter at -1, the BS rejects the next SC operation with error code 22 "attach propagate message malformed" and drops the connection, causing a ~5s reconnect loop. The attPrp payload itself was fully spec-compliant — the error text is misleading.

**How to apply:** Any change to connection/session handling must keep: fresh `snScUuid` per connection OR true resume with opId counter restored from `snScOpId`. Also: BSSCI `error` messages must be handled explicitly in the message loop, not fall through to "Unknown message type".

**Update (July 2026, real root cause):** The session-UUID fix alone was NOT sufficient. The actual cause: BSSCI **v1.1.0 changed the attPrp field set** — `bidi` was removed (replaced by mandatory `epClass`: 'z'=uplink-only, 'a'/'b'/'c'=downlink classes) and `syncBurst` became mandatory. Sending the 1.0.0 layout to a 1.1.0 BS triggers error 22. `nwkSnKey` is Numeric[16] (array of ints) in BOTH spec versions — a bin-encoding experiment was a dead end. Fix: store the BS protocol version from its `con` message per connection and build attPrp version-dependently. The official v1.1.0 spec PDF is user-provided (confidential, not public); v1.0.0 rev1 is public on developers.mioty-alliance.com. Lesson: on "malformed" errors from a BS announcing a newer BSSCI version, diff the spec versions' field tables first.
