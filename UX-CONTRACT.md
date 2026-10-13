# UX Contract

## Product context

Homeowner monitoring a local ESP32 boiler interface. English presentation, browser-local formatted timestamps, WCAG 2.2 AA target. Visual context: DESIGN.md.

## Business-context sources

| Domain | Source | Type |
|---|---|---|
| Boiler control boundary | User request: improve UI and updates without complex firmware changes | Explicit scope |
| Authorization/read-only | BSB_LAN.ino / default_flag and JSON API | Existing implementation |
| Data formats/endpoints | openapi.yaml | API contract |
| Parameter readiness | docs/en/install.md | Upstream documentation |

## Canonical UI Map

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
|---|---|---|---|---|
| Select/Listbox | Existing server select fields, ui/console.css | Existing endpoint contract | native | Keyboard and mobile settings |
| Form | Existing server form, ui/console.js enhancements | Existing endpoint contract | edit | Labels and secret masking |
| Scrollbar | ui/console.css | DESIGN.md | global | Browser computed style |
| Toast | Persistent shared notice in ui/console.js | Async response outcome | inline status | Failure tests |

Storage operations use an app-owned native dialog. Format requires typing FORMAT; deletion names the affected file. Cancel and Escape restore focus.

## State and navigation

Existing URL endpoints, passkey prefix, raw dumps, JSON API and authentication remain intact. Native settings submissions retain their server behavior; this patch does not change their payload or result contract. Interface navigation uses real anchors. No automatic settings save. Native selects retain platform popup ownership.

## Data and updates

One overview operation at a time; device status precedes reading requests. Only definitions present in the active parameter table enter the overview request. Auto refresh defaults off, uses 30 seconds after completion, pauses when hidden and stops after three consecutive failures. Each request has a 60-second timeout; leaving the page cancels browser work. Cancellation does not claim to stop server work. Manual refresh remains available. Missing, failed, stale and valid zero readings are distinct. Latest values remain visible and are labelled stale on failures.

## Search and accessibility

Search is local, immediate and composition-safe; clear returns focus to the input. Search is intentionally transient to avoid changing legacy firmware command URLs. Native table semantics, labels, focus rings, accessible notices and 640px responsive reflow. No browser alerts or synthetic control actions. JS failure leaves the server-rendered interface usable.

## SD storage

Olimex ESP32-POE-ISO only. The SD page inherits HTTP authentication and passkeys. Mutation requests are POST with a rotating nonce in the body, maximum 180 bytes and a bounded read timeout. Authentication must be configured. Server rejects mutations when storage is internal flash, SD logging/averages/telegram logging or SD web serving is active. Format requires explicit FORMAT confirmation. Mount never formats on failure; only the confirmed format path may prepare an unreadable filesystem. Only removable SD is accessed. File actions are limited to 100 root entries with validated ASCII filenames; no traversal or recursive deletion. Downloads are capped at 1 MiB/15 seconds. UI never claims a timed-out operation was cancelled. Real destructive actions are not exercised on a user's card during verification.

Storage management shares the existing SD_MMC object and upstream logging files. Configure logging uses the existing Settings endpoint; no new boiler message decoding or automatic parameter writes. Storage audit rotates at 256 KiB to one previous file, records boot identifier, uptime, action, validated filename and result, and excludes credentials. Format erases previous audit history; the successful format creates a new entry. An unavailable card cannot retain an audit entry.
