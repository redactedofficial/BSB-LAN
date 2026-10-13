# Circuit-1 water cycles and heating calendar

This Home Assistant package uses Frederik's original BSB-LAN MQTT discovery.
It does not replace the ESP32 application, boiler protocol, decoder or burner
controls. The included entity IDs and English enum labels match the verified
LMS15 configuration; review them against your own discovery before installation.

`manual-return-heat.yaml` controls **heating circuit 1 only**. DHW and other
heating circuits remain independent. Return temperature is the water entering
the boiler, not the room temperature or a measurement of the whole buffer tank.
An installation with a shared solar/radiator buffer needs that distinction.

## Setup

1. Keep original BSB-LAN MQTT enabled, with plain values and Home Assistant units.
2. Add a native **Local calendar** named **Heating** (`calendar.heating`).
3. Install the YAML file in the Home Assistant packages directory, add the
   packages include if absent, validate configuration and restart Home Assistant.
   Do not install a second copy of this controller under a different filename.
4. Initialize the controls: manual return cutoff **45°C**, maximum cycle
   **60 minutes**, calendar event target **50°C**, between-events target **40°C**,
   restart differential **2°C**, and maximum requested HC1 flow setting **55°C**.
   Numeric helpers restore their values rather than resetting operator choices.
5. Add the cards from `heating-dashboard.example.json` to an existing dashboard,
   preserving its other cards. Gas helpers are described in `gas-calibration.md`.
6. Add your actual heating periods to the calendar, then enable calendar heating.
   It starts paused and pauses again after a Home Assistant restart.

The calendar reconciles the current events every minute as well as on start/end
triggers. It checks all overlapping events, so the end of one event does not
select the lower target while another is still active. During any event it uses
the event target; outside events it uses the lower target. A new cycle starts
below the target by the configured differential. There is a ten-minute minimum
gap after a completed cycle. This limits rapid cycling; it is not an AI model or
an annual gas allowance enforcement mechanism.

Manual Start pauses calendar heating and runs a single cycle. Stop pauses the
calendar too, so the scheduler cannot immediately restart the stopped cycle.
A cycle ends in Protection mode, while retaining the boiler's frost protection.
Ordinary independent DHW charging can still operate.

## Thermostat override and ownership

Without the override switch, the existing thermostat must request heat.
The verified controller assigns H5 to **Room thermostat HC1 (5977 = 18)**.
Override retains that assignment. It temporarily changes **H5 contact type
(5978)** to make the observed contact a heat request: an open contact uses
normally-closed interpretation; a closed contact uses normally-open
interpretation. If the contact changes during an owned cycle, the controller
adjusts its interpretation. The raw H5 contact remains visible in the panel.

The controller also requests a fixed HC1 flow setting **5°C above the return
target**, bounded by the configured ceiling. This is parameter 742, not the
measured boiler-temperature target; the boiler may calculate a different
internal target. The ceiling is not a replacement for its factory temperature
limits or any independent protection required by the hydraulic system.

Only three existing controls are writable by the controller: mode **700**,
contact type **5978**, and flow setting **742**. It never writes the thermostat
role, safety limits, gas valves, burner commands, DHW settings or other circuits.
On completion it restores contact and flow settings still owned by the cycle.
External changes relinquish ownership and pause scheduling; an external mode
selection is preserved. An externally changed contact or flow setting is not
silently overwritten with an old snapshot.

## Readbacks, faults and recovery

Starts require fresh MQTT readbacks and no boiler error. Writes are acknowledged
against both the native entity and an independent MQTT receipt record. Receipt
timestamps retain subsecond precision: HA suppresses identical entity values and
rounds timestamp sensor states to seconds. Neither can serve as reliable command
acknowledgement alone. Read-only `/poll` requests and commands are non-retained.

The recovery journal is explicitly saved before boiler writes. The controller
serializes starts, stops and thermostat-request refreshes. It stops and pauses
the calendar on a boiler error, stale feedback or the maximum run time. Failed
stops retain their journal for retry and raise a local notification. Restart
recovery stops an unfinished cycle instead of resuming it automatically.

**The return-water cutoff runs on Home Assistant.** A server or network outage
can prevent it from sending a stop. The boiler's factory protections remain;
this package does not provide an ESP32 watchdog or an independent hardware
temperature cutoff. Do not treat it as either. Leave the native limit and
hydraulic protections configured for the installation.

## Validation

Fourteen focused tests cover the actual Jinja decisions, missing/stale feedback,
write allowlist, fresh repeated readings, ownership/restoration, fault handling,
contact interpretation, switching off an owned override, persisted recovery journal, overlapping events and
timezone-aware event boundaries. Run with Python, PyYAML and Jinja2:

```text
python test_water_calendar.py
```

Home Assistant 2026.10 accepted the deployed package. A real manual circuit-1
cycle ran with H5 still assigned as a thermostat, reached the 45°C return cutoff,
selected Protection, and restored the original contact type and flow setting.
The boiler reported no error on that route. Water can overshoot the threshold
between readings and during pump overrun; the target is not a hard thermal cap.

The BMS overview was checked at desktop and phone widths. A full 50°C calendar
cycle has not been run; no heating periods were invented for the user. Calendar
reconciliation was verified on the live empty calendar, with overlapping windows
and boundaries covered by the tests.

For rollback, first stop an owned cycle and verify the original contact/flow
settings. Back up the current package and dashboard, then restore the previous
package or remove its include and restart HA. Removing the package during an
active cycle cannot restore boiler settings automatically.
