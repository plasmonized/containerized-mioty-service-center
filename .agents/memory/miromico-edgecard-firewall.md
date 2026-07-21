---
name: Miromico/ifm EdgeCard gateway firewall
description: Why a mioty EdgeCard silently fails to reach a BSSCI service center on non-default ports
---
# ifm/Miromico mioty gateway blocks BSSCI traffic on non-default ports

The ifm IIoT mioty gateway (EdgeCard behind it at 172.30.1.2 on internal net mioty0) has a built-in iptables FORWARD chain that only allows NEW connections from the card to **destination port 16017** (mioty0 → end0). Everything else from the card is silently DROPped — the card retries forever, no packets ever leave the gateway, and no error is visible anywhere (card API reports config applied fine).

**Why:** Diagnosed July 2026: card config, certs, NAT (MASQUERADE), and network were all correct, yet zero connection attempts arrived at the service center. `iptables -L FORWARD -n -v` showed 127 dropped NEW packets from mioty0.

**How to apply:** When a mioty base station behind this gateway won't connect, either map the service center's external Docker port to 16017 (recommended — survives reboots) or persist a custom ACCEPT rule on the gateway (fragile). Check FORWARD counters early: it's the fastest way to see if the card is trying. tcpdump is not installed on the gateway; use iptables packet counters or /dev/tcp tests instead. The card's HTTP API is at http://172.30.1.2/cgi-bin/{config,status} (gateway shell only).
