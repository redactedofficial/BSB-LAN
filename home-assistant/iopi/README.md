# IO-PI

Raspberry Pi 3 B+ node with verified TLS MQTT, native Home Assistant discovery,
26 usable header GPIO observations, eight relay outputs and a Delta contact input.
GPIO0/1 remain reserved for HAT identification; power, ground and internal SoC
lines are not controls. No HTTP service is exposed.

## Pin assignments

| Physical pin | BCM | Assignment |
|---:|---:|---|
| 11 | 17 | R1 — Boiler request |
| 13 | 27 | R2 — Radiator pump |
| 15 | 22 | R3 |
| 16 | 23 | R4 |
| 18 | 24 | R5 |
| 22 | 25 | R6 |
| 29 | 5 | R7 |
| 31 | 6 | R8 |
| 37 | 26 | Delta demand input |
| 39 | Ground | Isolated contact return |

The commissioned HIGH-trigger profile uses active_high and initially requests
LOW/off on all outputs; live ON tests are not part of installation. Verify the
trigger polarity, 3.3 V input compatibility and actual switching hardware first.
The 250 VAC marking alone is not an inductive-load rating. GPIO drive readback
does not confirm a closed relay, pump rotation, flow, burner firing or water heat.
The generic relay board has no identity interface and cannot be automatically
detected from GPIO levels. Floating unused GPIO readings are not device presence.

Only R1/R2 and Delta get functional aliases. Other GPIOs retain GPIO numbers;
unused relays retain R3–R8. All usable pin modes/functions and physical positions
are published, including alternate-function pins, without changing their mux.

## Daily room heating and manual cycles

Before commissioning R1, confirm the native boiler accepts its external HC1
thermostat contact: R1 open must report no demand and R1 closed must report
demand. Native HC1 Protection mode can reject that demand even while the Pi
correctly drives the relay. Enable the boiler's normal heating mode (Comfort
for this profile) and a compatible commissioned flow target using BSB-LAN,
with acknowledged readback. A 45°C return cutoff needs flow-temperature headroom;
50°C flow is the commissioned example. Do not change safety/OEM limits or the
thermostat-input role to force operation. The node does not repeatedly overwrite
native mode/flow choices; selecting Protection later remains an operator choice.
The relay state reports a request, and native DHW priority can delay space heat.

`daily-heating.yaml` replaces the legacy room-heating package in Home Assistant.
Do not install it alongside that package: the existing helper IDs and Heating
calendar are intentionally retained. The DHW package and its calendar are unchanged.
The HA coordinator publishes a non-retained daily permission every 30 seconds,
expiring within 75 seconds (or at the current event's end). Calendar gaps, warm
or unavailable weather, a paused master, an automatic block or a heating-fault
flag deny permission. Cold allowance can extend the windows, including overnight
when enabled. Existing daytime half-hour events need no changes.

In Thermostat mode, **Delta demand AND fresh allowed daily permission** are both
required. An open or unavailable Delta contact never starts R1 or R2 automatically.
R2 circulates buffer heat while demand remains. R1 can charge only with fresh,
valid boiler return/error feedback, below the daily return target minus the
adjustable differential, after five seconds of pump priming. The return target
stops R1; R2 can continue using stored heat. A charging cycle has a fixed one-hour
ceiling and a ten-minute recharge rest. Renewed permissions do not extend that
charging deadline. The managed pump can keep circulating beyond an hour only
while Delta and the short-lived server permission remain valid. A missing boiler
reply blocks R1 but still permits that circulation; a confirmed boiler error
blocks both automatic requests.

R1 ON requests an explicit bounded Manual cycle; Off ends it. The local coordinator primes
R2 for five seconds before R1, stops at the return-water cutoff (default 45°C),
then keeps R2 on for 120 seconds. Manual overrides Delta/calendar comfort demand
and pauses the daily master; it never overrides native boiler protections.
Independent R2 control also pauses automatic ownership. GPIO26 uses a pull-up,
but `thermostat.connected` stays false until its isolated jumper wiring is fitted.
The raw pin can be observed; the heat-demand entity remains unavailable meanwhile.
Changing a raw GPIO level never starts heating.

For boiler charging, live BSB-LAN return parameter 8314 and error parameter 6700
must both arrive within 45 seconds. MQTT 5 subscriptions suppress retained
subscription snapshots while accepting newly published readings from the
gateway's retained state stream. Missing/invalid temperature, any boiler error,
network loss or the fixed one-hour cycle deadline ends the request. Duplicate
Manual commands cannot extend the deadline. Unavailable boiler feedback blocks
heat, including when the boiler is powered off. Only read/poll access to these two BSB
parameters is granted; IOPI cannot modify the boiler's BSB settings.

R2 can also circulate independently on a five-minute lease. R3–R8 use individual
five-minute leases; ON renewals cannot exceed the one-hour continuous ceiling.
The node starts Off after restart/reconnection. Home Assistant can re-arm
Thermostat mode when the saved daily master is enabled, using a new permission.
Manual once is never resumed. Actual mode is
acknowledged only through state telemetry; retained/duplicate/stale commands are
rejected. Systemd watches main-loop liveness. A GPIO fault latches outputs off.
No software can guarantee pump run-on through power loss or a hardware failure;
native boiler limits and required physical interlocks remain in place.

Room scheduling no longer rewrites the boiler's H5 contact interpretation or HC1
mode/flow settings. Delta is observed on the Pi as an isolated contact. Native
boiler controls determine whether a relay request produces flame. DHW keeps its
separate native controls. Opening dashboards sends no hardware command.

## Deployment and operation

Install Raspberry Pi OS packages `python3-paho-mqtt`, `python3-gpiozero` and
`python3-lgpio`. The service runs as unprivileged `iopi` with GPIO/video groups.
Source: `/opt/iopi`; root-owned configuration and scoped password: `/etc/iopi`.
Credentials are provisioned from local ignored `secrets/`, never application
archives or Git. `config.example.json` is deliberately uncommissioned.

Run checks without hardware/network:

```sh
python3 iopi.py --config config.example.json --check
python3 -m unittest -v test_iopi
# With PyYAML/Jinja2 installed, also test the actual HA schedule templates:
python3 -m unittest -v test_daily_heating
```

For a new deployment, `make_config.py --broker mqtt.example.org --confirmed-high-trigger
--output config.json` creates an enabled HIGH-trigger profile. It never overwrites
an existing file; omit the confirmation flag for an uncommissioned profile. Do not
ship config.json. Inspect that profile before installing. Set `thermostat.connected`
true only after fitting and verifying the isolated contact. First install uses
`sudo sh install_node.sh /absolute/path/to/iopi-stage` and refuses to replace an existing config.
Updates require backing up `/etc/iopi`, `/opt/iopi` and the service first.
Watch status with `systemctl status iopi` and `journalctl -u iopi`.
Control/audit transitions are capped at three 1 MB rotated files plus the active
file in `/var/log/iopi`. No secret payloads are logged.

MQTT prefix: `iopi/bmsiopi`; commands: `relay_N/set` with non-retained ON/OFF,
`heating/mode/set` with Off/Thermostat/Manual, and `heating/cutoff/set` with an
integer 30–55. Node and each observation publish separate availability. Sensor
states are non-retained and expire; discovery/availability are retained.
The daily coordinator additionally sends `heating/policy/set` JSON with boolean
`allowed`, numeric `target` (30–55), `differential` (1–5), Unix `expires` no more
than 90 seconds ahead, and a short `reason`. Retained, expired and malformed
policies cannot grant heat. Scope broker ACLs to this one extra command topic.

To disable output control, stop the service (allowing pump run-on), set relay
enabled flags false, and restart. To remove the deployment, stop/disable only
iopi, restore its prior service/source/config, and remove only its broker ACL,
password entry and HA dashboard/discovery. Do not restore old whole-broker files
over unrelated changes. The broker provisioning script stores a protected
pre-change backup and rolls back its files if reload fails.

Import `dashboard.json` into the Home Assistant dashboard's native raw configuration
editor to create the Overview and GPIO views. Add `bms-section.json` as a section
in an existing BMS dashboard. Entity IDs use the fixed `bmsiopi` identity; check them
if Home Assistant already contains conflicting entities. The dashboard is built
from native cards and requires no custom frontend components. The broker setup
script is specific to the existing BMS Mosquitto layout; inspect paths and user
blocks before using it on another broker.

Sources: [Pi GPIO](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#gpio),
[GPIO Zero](https://gpiozero.readthedocs.io/en/stable/api_output.html),
[MQTT discovery](https://www.home-assistant.io/integrations/mqtt/#mqtt-discovery).
