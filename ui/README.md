# Refined UI

Interface and SD storage customisation of BSB-LAN: embedded light-theme interface, responsive navigation, read-only overview, searchable parameter pages and settings accessibility improvements.

The bus driver, parameter decoder, device-specific table and boiler write-protection configuration are unchanged. The main firmware has eight added lines and a lower SD clock setting for an authenticated SD route and POST body length; storage operations live in a separate board-specific header. No boiler write endpoint is added. Settings retain upstream behaviour and authentication. The overview uses existing `/JI` and `/JQ` APIs and requests only parameter definitions present in the active table.

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

Preview paths: `/` for available readings, `/basic/` for missing definitions, `/offline/` for network failure, `/C` for settings and `/K` for category filtering, `/SD` for storage management. Device configuration writes and parameter downloads are not simulated. Browser validation covers these UI states; actual device and bus checks must also be performed after flashing.

Upstream attribution and licence remain in the root README. This is a custom UI branch, not an official BSB-LAN release.

SD management is exposed at /SD on ESP32-POE-ISO. Supports status/capacity, mount without formatting, unmount, root-file downloads and confirmed deletion, and confirmed full-card format using public ESP-IDF APIs. Formatting can prepare an unreadable filesystem after typed confirmation; card communication must work first. SD access uses a 10 MHz clock. Stop SD logging, averages, telegram logging and SD web serving first. No internal flash operations. Downloads limited to 1 MiB. Preview never performs storage actions. Format hardware validation requires a disposable test card and is not performed on user data.

Storage management shares the existing SD_MMC object and upstream logging files. Configure logging uses the existing Settings endpoint; no new boiler message decoding or automatic parameter writes. Storage audit rotates at 256 KiB to one previous file, records boot identifier, uptime, action, validated filename and result, and excludes credentials. Format erases previous audit history; the successful format creates a new entry. An unavailable card cannot retain an audit entry.
