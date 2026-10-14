# One-time hot-water / store-charge requests

`dhw-calendar.yaml` adds an owned one-time DHW request on original BSB-LAN.
It uses the boiler's **B3 store/DHW probe (8830)**, not a tap-outlet thermometer
or a measured temperature of all 500 litres.

The requested helper accepts **20–75°C**, as requested. Normal boiler writes are
accepted only from **35°C to the smaller of 60°C and fresh native maximum 1614**.
The [Luna Platinum+ manual](https://baxi.at/wp-content/uploads/2024/06/Luna-Platinum-1.pdf)
specifies the normal DHW range 35–60°C. The actual device reports 1614 = 60°C;
that OEM parameter is read-only in this integration. Out-of-range requests are
blocked with an explanation and no boiler write. The separate hygiene setpoint
is not used to bypass the normal target ceiling.

Set `input_number.bsb_dhw_once_target` and press **Heat once**, or use a
45/50/55/60°C preset. `input_number.bsb_dhw_once_minutes` bounds the request to
1–120 minutes; this installation defaults to 60. The preset field overrides the
requested target for that cycle without changing the stored helper selection.

## Ownership and cleanup

The existing serialized calendar controller routes manual start/stop/monitor
before its calendar gate. Manual requests work while the calendar is paused;
automatic calendar and hourly top-up writes wait during an owned manual cycle.
A duplicate start does not change the target or deadline.

Fresh mode, target, release, maximum, temperature, DHW status and native error
replies are required. If the store probe already meets the target, no settings
are changed. Native hygiene status blocks taking ownership. Existing top-ups
must stop with acknowledgement before the manual request can take over.

The original target/release, cycle target and deadline are journalled and saved
before On. The controller confirms Off, release 24h/day, the requested target,
then On. The original firmware controls ignition, hysteresis, pump operation and
all boiler protections. A request is not a guarantee of continuous burner firing.

Temperature checks run every ten seconds during active requests. At target,
deadline, manual Stop, master Pause, missing feedback or native error, the
controller confirms Off, polls fresh settings, and restores only still-owned,
still-permitted target/release values. It never restores an old On mode. An
unconfirmed stop or restoration retains the journal, blocks new starts and
retries. Stops and restoration depend on HA/MQTT connectivity.

Server startup cancels an interrupted cycle and cleans up its journal. External
mode/target/release changes or native hygiene control release ownership and pause
the calendar without overwriting those external settings. **Stop one-time cycle**
affects the owned cycle; the main calendar can resume afterward if still enabled.
**Pause & stop DHW** pauses automatic DHW and stops an owned one-time cycle too.

## Weekly hygiene proposal

`weekly-hygiene.pending.yaml` is a reviewable **disabled** native-settings plan,
not an installed weekly heating job. The device currently reports hygiene Off,
65°C hygiene target and a ten-minute dwell. Those readings refresh without
changing any hygiene parameter.

The photographed HAJDU PT500CF has a separate through-flow stainless tap-water
coil. No thermostatic tap-water mixer was identified. Heating the buffer does
not certify treatment of the coil or downstream pipework. Confirm the potable
path, anti-scald protection and suitable temperature/hold procedure before
enabling the weekly native cycle. The ordinary calendar must also be prevented
from cutting that cycle short. This integration does not claim sterilisation.

## Verification

Run `python test_dhw_calendar.py` with PyYAML, Jinja2 and timezone data. The
26 focused tests cover the shared calendar, hourly cap, manual target/ceiling
bounds, fresh feedback, snapshot deadlines, duplicate starts, owned restoration,
external control and startup cleanup. HA 2026.10 validation and real request /
timeout / Off acknowledgement checks were also performed on the installation.
