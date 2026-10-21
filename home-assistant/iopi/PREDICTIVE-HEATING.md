# Predictive heating in the existing BMS

The optimizer is a production extension of this app, not a replacement actuator
controller. Home Assistant remains the only automatic room-policy writer, IO-PI
owns R2 and Delta, and `bsbheat` owns native 700/742/5978 requests and restoration.
The optimizer's MQTT account cannot write native `/set` or IO-PI command topics.
No combustion, gas-valve, safety-limit or DHW capability was added.

## Control flow and production fallback

`BSB statuses + timestamped optional sensors → validated telemetry → SQLite →
RC identification / annual ledger → HiGHS MPC → independent supervisor →
75-second recommendation → existing HA coordinator → existing IO-PI/BSB bridge`.

HA first publishes its unmodified calendar/weather permission as optimizer context.
Only a fresh, schema-validated, authoritative production recommendation may
restrict that permission or change its return target within 30–55 °C. It cannot
open an otherwise blocked calendar, defeat Delta, release a manual stop, or enable
new native write parameters. The native flow request remains return target +5 °C,
capped at 60 °C. The existing manual cutoff and native safety limits still apply.

`production` is the deployed mode. This is **not shadow mode**. Until actual room
temperature, calibrated H/C, commissioned efficiency and 24 hours of valid hourly
weather are present, production deliberately runs the established conservative
controller. It does not invent indoor temperature from the room target or 8742.
Loss of the optimizer or an expired recommendation returns HA to that controller.
Weather outage preserves scheduled Delta heating; it cannot invent a cold-weather
overnight window. Explicit blocks and the 25 °C warm-weather gate remain effective.

Manual Pump only, Pump: Auto, Stop heating & pump and the bounded cold boost keep
their existing ownership. Calendars continue. Stop retains existing two-minute
pump afterrun when required by an active room charging request. DHW is separate.
R1 stays physically off. Software cannot guarantee a native stop during a total
BMS/gateway outage: native limits still apply, and the existing bridge journals
owned settings for recovery.

## Physical model and optimization

The model is `C dT/dt = η Qfuel + Qsolar + Qinternal − (H + Hwind v)(T − Tout)`.
Units: C kWh/K, H kW/K, heat/fuel kW, elapsed time hours, wind m/s. Each 15-minute
step uses the exact exponential solution with constant inputs over that step.
Solar gain is radiation × calibrated effective gain, not a claim of solar tank heat.
Missing radiation contributes no assumed solar gain. Cloud cover is retained as
forecast context; it is not converted into invented irradiance. Cold-side forecast
uncertainty is explicit and increases with lead time.

SciPy HiGHS solves a constrained mixed-integer problem across 24–48 hours.
Variables include fuel power, room temperature, comfort shortfall, burner on/start,
control variation and optional verified tank transfer. The objective combines
fuel price (or an explicitly unpriced energy proxy), comfort, annual allowance
pressure, cycling, variation, forecast risk and soft daily preferences. Pump
electricity and transfer losses are included for verified storage transfer. The
electricity assumptions are configurable estimates, not physical power readings.

Hard constraints include bounded room temperature (15–24 °C default), fuel
minimum/maximum, scheduled/cold gas windows, minimum run/rest times, nonnegative
storage and a finite solver deadline. Storage circulation has its own on/start
variables and run/rest constraints. Native afterrun and anti-cycling remain
authoritative. A house already below the hard minimum can make MPC infeasible;
the conservative existing heat controller then remains available.

Only the first validated action is eligible for execution. A plan is valid for at
most 15 minutes; the supervisor rechecks fresh feedback every 30 seconds and HA
checks the expiring recommendation again. Solver failure, timeouts, uncalibrated
inputs and invalid residuals produce fallback. A ≥5 °C forecast jump invalidates
the current planning slot early. Local daily preferences use actual Budapest
dates, not fixed 96-sample days. An optimizer recommendation may defer gas when
predicted comfort is maintained; a manual heat boost retains its explicit override.

## Calibration and optional hardware

No real room or outdoor reading is currently supplied by 8740/8700. HA weather
is explicitly an outdoor estimate. H/C learning needs measured room observations
and trusted delivered heat. `allow_estimated_heat_identification` is false by
default; opting in requires a commissioned efficiency and clearly labels fuel × η
as estimated delivered heat. Online RLS uses forgetting, bounded innovations,
parameter bounds, excitation checks, at least 72 samples and an error threshold.
Unexcited data cannot commission a model. A manually approved model needs H, C
and `calibration_source`; initial numerical RLS values are never a calibrated model.

Optional external sensors publish JSON `{ "at": "2026-10-21T12:00:00Z",
"value": 18.1, "unit": "°C" }` under `bms/heating_sensors/…`. Add a verified
physical identity, unit, range and topic under `external_sensors` in config.
Supported keys: `room_actual`, `tank_top`, `tank_middle`, `tank_bottom`,
`flow_m3h`, `supply_actual`, `return_actual`, `pump_feedback`, `delivered_kw`.
The publisher needs its own scoped broker permission. Sensor payload timestamps
must be UTC/offset-aware, within 180 seconds, finite and match the configured unit.
Relay readback never stands in for a physical pump/flow sensor.

For a water loop with verified flow, `QkW = 1.163 × flow_m³/h × (Tsupply−Treturn)`.
No flow means no accurate delivered power. Flow for glycol needs another validated
fluid model. Fan speed and nominal boiler power are not heat meters.

Tank energy is `0.001163 × litres × max(0, representative_average−reference)`.
B3 alone does not establish that average. Set `tank_average_verified`, configured
sensor keys/weights and `hydraulics_verified` only from a verified installation.
Until then, new MPC tank dispatch stays disabled. Existing operator-selected
stored-heat controls retain their semantics. A rising B3 trend is labelled
unattributed; it does not prove solar input and cannot start the pump by itself.
Optional measured supply/return can reject nonbeneficial storage circulation.

## Accounting, MVM and annual forecasts

SQLite stores UTC observations, canonical fuel intervals, counter baselines,
forecast issue times, plans, matched predictions, invoices and rejection events.
8378/8379/8380 are independent estimated fuel counters. Their 8381/2/3 aliases
are not ingested or added. Total fuel is not summed with its heating/DHW parts.
Counters are monotonic-differenced with reset detection, unit checks, out-of-order
rejection, a plausible-rate ceiling and 1 kWh quantization tolerance. Resets leave
uncovered time; history gaps and daily boundaries use proportional elapsed-time
allocation, explicitly an estimate. The maximum interval rate is not a heat meter.

There is no configured supported MVM account connection. Billing imports are
explicit manual data, never an invented API or tariff. Actual m³ conversion
requires dated heating value in MJ/m³ **and** the applicable correction factor.
Different date intervals may use different factors. Overlapping factors are
rejected. Without them, new volume/cost metrics remain unavailable.

Configure `billing` with `year_start`, exclusive `year_end`, `allowance`,
`allowance_unit` (kWh/MJ/m3), optional allowance conversion, dated `conversions`,
verified marginal `tariffs` and optional 12-month `seasonal_allocations` fractions.
Tariffs require currency, `verified_source`, `price_per_kwh` and ordered cumulative
`up_to_kwh` bands (last may be null). These are energy charges only; include fixed
fees/taxes separately when comparing a full invoice. Seasonal allocations are
reported context, not rigid monthly quotas or extra consumption targets.

Invoice JSON example (illustrative, replace with the actual invoice):

```json
[
  {"id":"invoice-unique-id", "start":"2026-07-01T00:00:00+02:00",
   "end":"2026-08-01T00:00:00+02:00", "consumption":1234,
   "unit":"MJ", "source":"Actual MVM invoice reference"}
]
```

Import with `optimizer_tools.py import-bills --database PATH --input invoice.json`
while the worker is stopped, then start it. Unique invoice IDs make updates
idempotent; overlapping authoritative invoices are rejected. For volume invoices,
include `heating_value_mj_m3` and `correction`. Invoices take priority over overlapping
controller estimates, never double-counting both. At least 98% year-to-date
coverage is required before claiming a remaining annual allowance.

Seven-day gas forecasts need at least seven completed covered days, varied
degree-days and DHW history. Year-end demand also needs explicitly supplied
12-month `monthly_outdoor_normals_c`; beyond provider coverage these are labelled
climatology, not weather forecasts. Annual projection equals actual + forecast
remaining demand. Unused allowance stays available for that billing year. The
5/7 m³ preferences only penalize excess; neither rewards consumption nor cuts off
essential heating. Missing tariffs/history remain visibly unconfigured.

## Weather, timestamps and retention

`predictive-heating.yaml` reuses `weather.forecast_home`, fetching supported hourly
and daily forecasts every 15 minutes. Current provider coverage is shown honestly;
it does not synthesize 7–14 days of hourly data from daily values. If supported
coverage expands, up to 14 days are accepted. The first partial hour may use the
provider's current estimate. No unbounded forward fill through forecast gaps.

All integrations use UTC elapsed seconds; local days/schedules use
`Europe/Budapest`. 23/25-hour days, offset-distinct repeated times, Gregorian leap
exceptions and noncalendar billing years are tested. The planner identifies
15-minute slots by UTC epoch. Restart replaces a same-slot record rather than
duplicating it and requires fresh hardware feedback, not old retained messages.
Observations are kept 35 days, plans/predictions/audit 400 days; annual energy
intervals and invoices are retained. Queue sizes, payload lengths, polls, solver
time, memory and CPU are bounded. Journal rotation remains the host's policy.

## Deployment, verification and rollback

Python dependencies are in `optimizer-requirements.txt`, isolated from the existing
bridge environment. `bsb-optimizer.service` runs as unprivileged `bsbopt`, writes
only its state directory and uses scoped loopback MQTT credentials. Configuration
and credentials live under `/etc/bsb-optimizer/`; persistent state lives under
`/var/lib/bsb-optimizer/`. Keep authoritative private copies under `secrets/`.
Never synchronize that directory with public sources.

The service requires outbound weather only through existing HA; loss of internet
does not remove local Delta/manual control. `--check-config` validates before
startup. Source/schema tests and actual runtime logs both matter: HA's general
configuration checker does not validate every MQTT sensor option.

Run `python -m unittest -q test_predictive test_daily_heating test_bsb_heat_control
test_iopi`. Tests cover models, cold/warm cases, no-data fallback, billing overlap,
counter reset/restart, DST/leap years, safety/manual rejection and isolated replay.
No test energizes hardware. Run tests in the target Python environment as well.

`optimizer_tools.py import-recorder --database OWN_DB --input HA_RECORDER`
reads HA SQLite strictly `mode=ro`, validates unique parameter identities and
counter units, and writes only the app's ledger. Backfill must precede live counter
ingestion. `optimizer_tools.py backtest --database OWN_DB --config CONFIG
--output REPORT.json` opens history read-only and replays into a temporary store.
Simulation publishes only `simulation/…`, never instantiates MQTT or an actuator
client, and only uses forecasts issued at/before replay time. A history with no
actual room or archived forecasts reports fallback instead of invented accuracy.
Matched room and 15-minute fuel errors are scored only after observations arrive.

Disable the worker to fall back immediately after its 75-second lease, or select
`disabled` in HA. For full rollback stop/disable `bsb-optimizer`, restore the prior
room package from the timestamped backup, remove the predictive package, validate
HA and restart it, then restore dashboard configuration through the UI. Restore
broker ACL/password backups and reload Mosquitto only if removing the identity.
Do not restore HA `.storage` files directly while HA is running. Preserve the
ledger/invoices for later recovery. Existing native journals and IO-PI config are
never reset by this extension.

The native HA panel uses a current-state summary, Heating plan, Gas & allowance
and Heating diagnostics. Unknown values are visible; household controls retain
their established actions. Planning and cost metrics are not claims of measured
efficiency, guaranteed savings or confirmed water circulation.
