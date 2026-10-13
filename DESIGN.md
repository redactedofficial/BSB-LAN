---
version: alpha
colors:
  primary: "#0645ad"
  background: "#fff"
  text: "#111"
  border: "#aaa"
  danger: "#a40000"
typography:
  body:
    fontFamily: "Arial, sans-serif"
    fontSize: "16px"
    lineHeight: "1.4"
spacing:
  page: "16px"
  table: "4px"
omitted:
  - section: rounded
    reason: "Native browser controls retain their platform geometry."
  - section: components
    reason: "Native HTML elements, with no component framework."
---

# BSB-LAN MQTT minimal

## Overview

User-approved direction: Frederik's original plain panel, further reduced and
focused on functionality. English device-administration UI for a homeowner on
a laptop or phone. Status, parameters and essential settings only. No cards,
decorative icons, image assets, charts, fonts, animations or automatic polling.
Dashboards and seasonal gas budgeting live in Home Assistant.

The canonical source is ui/minimal.css. This document mirrors its variables:
primary → --link, background → --paper, text → --ink, border → --line,
danger → --danger. ui/build_minimal.py embeds CSS and JavaScript directly in
BSB_LAN/html_strings.h. Generated firmware assets are not edited separately.

## Typography

Arial and the browser's local sans-serif fallback follow the original panel.
Body and controls are 16px; the status heading is 20px. Content determines
height. Native input, select and button geometry remains platform-owned.

## Layout

960px maximum content width, document scrolling and simple table rows.
Navigation wraps. Settings rows stack below 600px; parameter tables retain
their own horizontal scrolling. There is no fixed-height application shell.

## Components

Real anchors for navigation; native forms, selects and buttons for control.
The shared notice reserves 24px and announces pending, success and errors.
Visible keyboard focus uses the link color. The browser owns scrollbar
geometry, native select popups and control geometry. Passwords remain masked.

## Verification

Compare status and settings at desktop and 390px widths. Check a native select
popup, keyboard focus, masked fields, save rejection and absence of overflow.
Read-only values never gain Set buttons. UI assets target less than 5 KiB.
