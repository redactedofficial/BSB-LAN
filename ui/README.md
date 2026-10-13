# Refined UI

Presentation-only customisation of BSB-LAN: embedded light-theme interface, responsive navigation, read-only overview, searchable parameter pages and settings accessibility improvements.

The main firmware, bus driver, parameter decoder, device-specific table and write-protection configuration are unchanged. No new write endpoint is added. Settings retain upstream behaviour and authentication. The overview uses existing `/JI` and `/JQ` APIs and requests only parameter definitions present in the active table.

Automatic refreshing is off initially, runs 30 seconds after completion when enabled, pauses in hidden tabs and stops after three failed attempts. Network operations run sequentially with a 60-second request timeout. Missing definitions, failed queries, disabled values, valid zero and stale readings have separate presentations.

Source assets live in `ui/console.css` and `ui/console.js`; regenerate the checked-in firmware include with:

```text
python ui/build_assets.py
node ui/test_readings.cjs
```

Build using the normal upstream configuration, your correct board and Minimal SPIFFS. Personal configuration, credentials and configured binaries are excluded from Git. Preserve your current device-specific file when updating. Do not replace it with the experimental generator's partial table.

The optional loopback preview uses **labelled sample data** and never connects to a heater:

```text
python ui/preview_server.py
```

Preview paths: `/` for available readings, `/basic/` for missing definitions, `/offline/` for network failure, `/C` for settings and `/K` for category filtering. Device configuration writes and parameter downloads are not simulated. Browser validation covers these UI states; actual device and bus checks must also be performed after flashing.

Upstream attribution and licence remain in the root README. This is a custom UI branch, not an official BSB-LAN release.
