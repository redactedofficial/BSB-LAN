---
version: alpha
name: BSB-LAN Heating Console
description: A local instrument panel for monitoring a Siemens-controlled heating system.
colors:
  primary: "#087e8b"
  background: "#eef3f8"
  surface: "#ffffff"
  ink: "#142b43"
  muted: "#526b83"
  border: "#cfdce8"
  danger: "#a22b34"
  warning: "#8b5900"
typography:
  body:
    fontFamily: "Aptos, Segoe UI, sans-serif"
    fontSize: "16px"
    lineHeight: "1.5"
  display:
    fontFamily: "Bahnschrift, Aptos, Segoe UI, sans-serif"
rounded:
  DEFAULT: "8px"
spacing:
  page: "24px"
  section: "28px"
components:
  button: {}
  table: {}
  field: {}
---

# BSB-LAN Heating Console

## Overview

Audience: the homeowner inspecting the boiler on a laptop or phone. Product/admin register, English UI, Central European home installation. The signature is a horizontal instrument strip of four temperatures above a quiet, precise readings table. A reading that is unavailable must never look like zero. No marketing hero, fabricated charts or remote font dependency.

The runtime canonical token source is `ui/console.css`; this document mirrors it. Semantic color keys map to `--primary`, `--bg`, `--surface`, `--ink`, `--muted`, `--line`, `--danger`, `--warning`. Typography maps to `--body` and `--display`; radius maps to `--radius`. `ui/build_assets.py` embeds the stylesheet and script in `BSB_LAN/ui_assets.h`.

## Colors

Cool blue-gray working background, white data surfaces and navy navigation. Teal denotes an available reading or primary action. Amber identifies an unavailable reading; red identifies interrupted or stale data. Every status has text as well as color.

## Typography

Local humanist font stacks, 16px body and tabular numeric readings. Display type is restrained to headings and temperatures. No downloadable font assets. Native controls receive explicit type and sizing.

## Layout

1400px maximum content width. Overview: heading/status bar, four-temperature strip, search, readings table and persistent notice. The table retains horizontal scrolling on phones; the temperature strip becomes two columns at 640px. Settings use document scrolling and reflow rows at 640px. Navigation wraps rather than clipping. No fixed-height shared page shell.

## Elevation & Depth

Flat surfaces, tonal separation and thin borders. No decorative shadows, gradients or blur.

## Shapes

8px controls and data surfaces, simple stroked instrument icons. Readings remain selectable text.

## Components

Shared presentation owners: `ui/console.css` and `ui/console.js`. All API-derived content uses text nodes. The overview sends read-only requests sequentially; automatic updates are opt-in. Focus rings, keyboard links, a clear-search action and live error states are consistent across screens. Native selects are intentional: the operating system owns their popup geometry. Local filtering is immediate and composition-safe. Existing server forms and parameter commands remain authoritative.

The image concept uses sample values solely to define typography and layout. Production uses actual API values or an explicit unavailable state. Navigation retains upstream endpoints and localized labels. These are intentional deviations from concept copy. No new date picker, selection, CRUD, modal or chart is introduced.

## Do's and Don'ts

- Do distinguish controller detection, successful reads and network reachability.
- Do preserve existing endpoints, authorization, raw downloads and read-only flags.
- Don't query missing parameter definitions or introduce overlapping polls.
- Don't infer physical sensors, heating circuits, writable parameters or operational values from menu presence.
