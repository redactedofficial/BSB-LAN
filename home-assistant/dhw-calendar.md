# DHW calendar on original BSB-LAN

`dhw-calendar.yaml` uses the original MQTT protocol, parameter definitions and
native boiler temperature control. It writes only DHW operating mode **1600**,
nominal target **1610**, and release **1620**. It does not change CH, thermostat
inputs, circulation, legionella settings or burner protections.

## Installation

1. Enable original BSB-LAN MQTT with plain values, destination 0 and prefix
   `BSB-LAN`. This example matches the verified English LMS15 parameter labels.
2. Add a Local calendar named **DHW heating**, entity `calendar.dhw_heating`.
3. Add timed events with **Daily** recurrence and no end date:
   - Morning preheat: **06:00–07:30**.
   - Afternoon hot water: **16:00–18:00**.
4. Install `dhw-calendar.yaml` once in the HA packages directory, validate the
   configuration and restart HA. Set `input_number.bsb_dhw_calendar_target` to
   **45°C**, then enable `input_boolean.bsb_dhw_calendar_enabled`.
5. Merge the DHW cards from `heating-dashboard.example.json` into the dashboard.

Use the Home Assistant local timezone for daily events. The verified instance
uses Europe/Budapest, so these wall-clock times follow daylight saving changes.
All timed events in this dedicated calendar use the adjustable target helper;
titles and descriptions do not encode commands. All-day events do not request
heat. Overlapping events stay enabled until the last active event ends.

## Behavior

During an event, the controller confirms release **24h/day** and the target,
then selects **On**. Release 24h/day allows HA to own the timetable. Between events
it selects **Off**, except during an enabled hourly top-up, rather than maintaining
a lower reduced target. It does not change the native stored program
4, so that original timetable remains available if manually selected again.

The boiler's own measured DHW sensor and control logic determine when the burner
fires. 45°C is the nominal tank-water target, not boiler return temperature and
not a guaranteed temperature of every part of a shared 500-litre hybrid tank.
Starting at 06:00 provides an hour of preheat before 07:00; actual readiness
depends on the starting tank temperature, heat demand and hydraulic system.

## Hourly five-minute top-ups

Enable `input_boolean.bsb_dhw_topup_enabled` alongside the DHW calendar switch.
At each full hour, including overnight, the same serialized controller checks
the current DHW temperature **8830**. Main calendar periods take priority, so a
top-up never competes with their longer charging windows. With a 45°C target,
start is permitted only **below 43°C** (a fixed 2°C start margin).

A started top-up ends at the target or at a **five-minute deadline**, whichever
comes first. The deadline is saved before native On and is never extended by
repeated triggers. A ten-second active-cycle check polls fresh temperature and
native feedback; a dedicated deadline trigger requests Off without first waiting
for new temperature replies. Actual target detection has polling/communication
delay. Off cancels the DHW request; room heating or pump overrun can continue.

`input_text.bsb_dhw_topup_status` reports a requested top-up, a warm-water skip,
missing feedback, target reached or timeout. A failed Off retains the active
journal and pending-stop flag, retries and raises a persistent notification.
Home Assistant startup cancels an interrupted top-up instead of restarting or
extending it. Enabled choices restore across restart. **Pause & stop DHW** pauses
both the main calendar and hourly starts; switching only top-ups off leaves main
periods enabled. Manual DHW controls require pausing the master calendar first.

The dashboard's **Check top-up now** invokes the same checks and consumes this
hour's one opportunity. Duplicate checks cannot start another top-up in that
hour. A missing/error reply or already-warm check also consumes the opportunity;
the next full hour provides another check. It is a capped top-up, not a promise
to finish a full recharge or to reduce gas use.

Heating-buffer water is not necessarily stored potable water. A 45°C target alone
does not provide Legionella control for stored tap water. Verify the actual tank
arrangement and the manufacturer's hygiene procedure; this package does not
configure or replace it. See [HSE's temperature guidance](https://www.hse.gov.uk/legionnaires/things-to-consider.htm).

The manufacturer's Luna Platinum+ manual states that DHW **Eco is not used on
this model**. A shared BSB-LAN enum may still expose it. Do not assume it provides
reduced-temperature tank charging. The schedule deliberately uses On/Off.
See [Baxi's model manual](https://baxi.at/wp-content/uploads/2024/06/Luna-Platinum-1.pdf).

Calendar starts/ends and a minute-level reconciliation keep the current state
correct after missed edges or restart. Enabled state restores across HA restart.
Starts require fresh native feedback and no boiler error. Failed stops persist
and retry every minute, with a local notification. Precise MQTT receipt timestamps
verify repeated values; an old retained value cannot confirm a new command.

**Pause & stop DHW** turns the schedule off and confirms native DHW Off. Manual
DHW mode/target controls can then be used without the calendar changing them back.
Re-enabling resumes the current event, if any. Manual room-heating controls and
the separate Heating calendar do not modify DHW. Original boiler priority applies
when room heating and DHW demand overlap.

Timed Off depends on HA, MQTT and the connection. During an outage the last native
DHW mode can remain selected until reconnection. The controller is not a device
watchdog or a replacement for native protections or cylinder hygiene settings.

## Verification and recovery

Seven focused tests cover real template boundaries, overlaps, all-day/missing
events, winter timezone offset, the DHW-only allowlist, precise acknowledgements,
and persistent stop retry. Run in an environment with PyYAML, Jinja2 and timezone
data (Windows may need `tzdata`):

```text
python test_dhw_calendar.py
```

HA 2026.10 configuration validation passed. Both daily recurrences were verified
in the live local calendar. The real boiler acknowledged target 45°C, release
24h/day, On, a Pause/Off and re-enable/On, with no error. Enabled state survived a
graceful server restart. This does not prove a complete afternoon cycle.

To roll back, pause and confirm DHW Off, then back up and remove this package.
Restore the previous native DHW target, release and mode if desired. Removing the
package alone does not undo already accepted boiler settings.
