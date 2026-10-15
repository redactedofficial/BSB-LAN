# Home Assistant and the minimal gateway

The firmware uses the original BSB-LAN MQTT implementation and Home Assistant
discovery. Writable temperature parameters are discovered as `text` entities;
enumerations become selects. Read-only diagnostics remain sensors. `Complete`
write access includes writable OEM parameters; it cannot turn a read-only
parameter into a writable one.

In the device Settings, enter your broker address, credentials, topic prefix and
device ID. Select MQTT logging, Home Assistant units and an interval of at least
30 seconds. Choose the parameters you want to poll. Home Assistant's MQTT
integration must use the same broker. Discovery runs after connecting; retained
availability and parameter state topics keep the normal BSB-LAN format.

The original command topics are retained:

```text
<prefix>/<device>/<category>/<parameter>/set    payload: desired value
<prefix>/<device>/<category>/<parameter>/poll   payload: empty
<prefix>/poll                                 payload: 710,8310,8700
<prefix>/<device>/<category>/<parameter>/status
<prefix>/status                               online / offline
```

Use the category and destination from discovery or `/JC` metadata, rather than
guessing them. Do not retain command messages. Use one controller for each
setpoint; competing automations can undo each other's changes. The existing
engine returns control to the default destination after temporary queries.

Keep the device on the private LAN. Remote web management belongs behind your
server's authenticated HTTPS proxy or VPN; the small local page retains the
original HTTP Basic authentication. MQTT TLS and certificate verification are
retained (do not define `NO_TLS` or the upstream insecure TLS opt-out). For TLS,
use the upstream `hostname:8883` broker syntax. This upstream version treats
port 1883 as plaintext and other ports as TLS. Broker ACLs should limit
Home Assistant and this gateway to their own state/command/discovery topics.

## IO-PI relay interface

[`iopi/`](iopi/README.md) adds a Raspberry Pi 3 B+ MQTT node with eight relay
channels, an isolated thermostat contact input and observations of all 26 usable
header GPIOs. Its native Home Assistant dashboard has Overview and GPIO views,
plus a read-only BMS section linking to the IO-PI controls. The node coordinates
boiler request R1 and radiator pump R2 with pump priming/run-on, fresh BSB feedback,
a return-water cutoff and bounded runtime. Credentials and commissioned local
configuration are excluded; the supplied example leaves outputs disabled.

## Seasonal estimated gas budget

Import `seasonal-budget.yaml` as a Home Assistant automation blueprint. Create
a monthly Utility Meter helper from the existing cumulative estimated gas
sensor. Its unit must be m³. Use separate enable/active input booleans and
saved/applied input numbers for each heating circuit. Set both numeric helpers
to a range compatible with the selected comfort-temperature entity (for example
5–35 °C, step 0.5), and keep the enable helper off during setup. The active and
numeric helper states must be restored across restarts; do not set an `initial`
value that discards ownership history. Select the circuit's writable comfort
setpoint entity, not a measured temperature or domestic-hot-water target.

Set the effective MJ/m³ conversion from your bill: heating value multiplied by
correction factor. Its default zero disables control. The annual planning
allowance and January–December weights are editable. The default 63,645 MJ
and winter-heavy monthly shape come from
[MVM's published allocation](https://www.mvmnext.hu/foldgaz/contents/Documents/Ugyintezes/Arkategoriak-szerinti-megosztas-modja/Arkategoriak-szerinti-megosztas-elszamoloszamlak-eseten.pdf?download=),
checked on 2026-10-13. The concession year is August–July; monthly allocation
is a planning input here, not a reproduction of billing periods, rounding,
special allowances or tariff prices.

Every five minutes the automation compares this month's estimated consumption
with the elapsed share of its seasonal target. If ahead, it lowers the selected
comfort target once by the configured setback, bounded by a minimum setpoint.
It restores the saved target when back within budget or when disabled, only
while the last applied value still matches. A manual change disables budget
ownership. Unknown consumption suspends new decisions; it is never treated as
zero. A one-minute acknowledgement timeout disables new budget commands;
ownership helpers remain available for reconciliation.

This is a soft budget using estimated gas, not a physical cap or a guarantee
of the lower Hungarian tariff. The monthly Utility Meter is incomplete until
its first full cycle. Calibration, actual meter readings, stale data and other
gas appliances matter. The automation adjusts space-heating comfort only;
hot-water demand and the boiler's autonomous protection still consume gas.
The minimum setpoint is not a measured room-temperature guarantee. Summer has
a much smaller planning allowance; no arbitrary 80% burner cycling is added.

Sources: [Home Assistant MQTT](https://www.home-assistant.io/integrations/mqtt/),
[Utility Meter](https://www.home-assistant.io/integrations/utility_meter/),
[blueprint schema](https://www.home-assistant.io/docs/blueprint/schema/),
[MVM current rules](https://www.mvmnext.hu/lakossagirezsi/gyakorikerdesek-foldgaz).
