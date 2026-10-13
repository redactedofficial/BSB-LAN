# Estimated gas consumption in Home Assistant

Keep the boiler's original gas-energy counter and calibrate derived readings on
the server. Do not reset a lifetime boiler counter to make a dashboard show zero.

## Energy source and period meters

LMS parameter 8380 is total gas energy for heating and hot water, in kWh. Use it
once as the Energy dashboard's gas source. Parameter 8383 can report the same
combined total; adding both would count the same gas twice. Writable component
counters 8378/8379 are not additional independent gas sources.

The discovery compatibility service adds `state_class: total_increasing` only
to known cumulative gas-energy sensor definitions, preserving their values.
It handles the original firmware's relative `~/status` MQTT discovery topics.
No bus decoder, controller parameters or control definitions are changed.

Create daily and monthly Utility Meter helpers from the original 8380 kWh sensor.
Leave delta values and net consumption off. This lifetime counter does not reset
on each ESP32 boot, so leave **Periodically resetting** off to preserve differences
through unavailable periods. Keep **Sensor always available** off; missing data
should remain visible. The first configured day/month are incomplete.

Use the original lifetime source in Energy, rather than a period helper. Energy
history starts with new recorded differences, not the entire lifetime total.
Do not configure cost estimates until the relevant tariff information is known.

## Convert kWh to meter m³

Read the bill's **Fűtőérték (MJ/m³)** and **Korrekciós tényező**:

```
effective MJ per meter m³ = calorific value × correction factor
estimated meter m³ = boiler kWh × 3.6 / effective MJ per meter m³
```

Convert the daily/monthly kWh helper into a template sensor for display and the
seasonal budget. Return `none` when any required input is unavailable or invalid;
never substitute zero consumption for a missing reading. Keep derived period
volume sensors separate from the raw Energy source. Changing a calibration
factor on a lifetime total can create artificial jumps in recorded statistics.

## Calibrate the boiler estimate

1. Record the physical meter `M0` in m³ and boiler 8380 `E0` in kWh together.
2. After enough consumption, typically 7–14 days, take paired readings `M1,E1`.
3. Calculate an estimate multiplier from the differences:

```
actual m³ = M1 - M0
raw estimated m³ = (E1 - E0) × 3.6 / effective MJ per meter m³
multiplier = actual m³ / raw estimated m³
```

Require positive, credible differences. Apply the multiplier to future derived
period consumption. Other gas appliances contribute to the physical meter but
are not represented by the boiler counter, so account for those before treating
the multiplier as a boiler calibration. A boiler estimate remains an estimate;
it is not a fiscal meter or a guarantee of a tariff allowance.

Sources: [HA gas energy](https://www.home-assistant.io/docs/energy/gas/),
[HA statistics requirements](https://www.home-assistant.io/docs/energy/faq/),
[Utility Meter](https://www.home-assistant.io/integrations/utility_meter/),
[MVM bill explanation](https://www.mvmnext.hu/foldgaz/contents/Documents/Ugyintezes/szamlamagyarazat/foldgazszamla-magyarazo.pdf).
