# Minimal gateway UX contract

Explicit user scope: compact MQTT gateway, very close to the original BSB-LAN
panel, all controller-permitted writes and server-based management. Retain the
bus, decoder, Frederik header and MQTT formats. DESIGN.md owns presentation.

Status performs no boiler queries or polling. Parameters use original category
pages and bounded category ranges; no unbounded dashboard table is introduced.
Settings expose network, authentication, MQTT, logging interval/list and write
level. Peripheral storage, card formatting, plots, raw dumps and OTA are absent.

Native controls and real anchors are authoritative. Browser-owned select
geometry is intentional. Shared inline status reserves space and announces
pending, accepted or rejected operations. No browser alert/confirm/prompt.
Password fields remain masked; no secrets enter browser storage or notices.

Writes require authentication, POST and a per-boot X-BSB-Token header. The token
is obtained from the authenticated page. Parameter writes use /JS with the
original JSON fields, preserve destination and report the engine's status.
Concurrent writes are rejected. A timeout leaves the outcome uncertain and
tells the user to read back before retrying. No automatic parameter retries.
Settings submissions prevent duplicate saves and return to Settings.

HTTP remains a small LAN administration surface; remote access is provided by
the user's HTTPS reverse proxy or VPN. MQTT TLS/certificate verification and
Home Assistant discovery remain upstream-owned. The broker governs MQTT
authorization. Firmware write levels are Off, Standard and Complete; intrinsic
read-only flags are preserved in every mode.

The seasonal budget is opt-in Home Assistant automation, based on estimated
monthly gas and editable monthly targets. It applies a bounded comfort setback
and restores only values it still owns. Manual overrides relinquish ownership.
It is not a physical m³ cap, tariff calculator or an 80% burner duty-cycle rule.
