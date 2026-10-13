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

No Table Selection, date picker, CRUD or destructive workflow is introduced.

## State and navigation

Existing URL endpoints, passkey prefix, raw dumps, JSON API and authentication remain intact. Native settings submissions retain their server behavior; this patch does not change their payload or result contract. Interface navigation uses real anchors. No automatic settings save. Native selects retain platform popup ownership.

## Data and updates

One overview operation at a time; device status precedes reading requests. Only definitions present in the active parameter table enter the overview request. Auto refresh defaults off, uses 30 seconds after completion, pauses when hidden and stops after three consecutive failures. Each request has a 60-second timeout; leaving the page cancels browser work. Cancellation does not claim to stop server work. Manual refresh remains available. Missing, failed, stale and valid zero readings are distinct. Latest values remain visible and are labelled stale on failures.

## Search and accessibility

Search is local, immediate and composition-safe; clear returns focus to the input. Search is intentionally transient to avoid changing legacy firmware command URLs. Native table semantics, labels, focus rings, accessible notices and 640px responsive reflow. No alerts, confirmations or synthetic control actions. JS failure leaves the server-rendered interface usable.
