# Heating-system identification map

This functional map combines photographed components with the tank manufacturer's
construction. Dashed house connections are hypotheses, not a traced piping plan.
No valve, pump or boiler command is attached to the map image.

The photographed label identifies **HAJDU PT500CF ErP, 500 L**. The heating water
in the buffer is separate from potable water in its stainless through-flow coil.
The other internal coil accepts heat from a boiler or solar circuit. The map
does not prove which actual ports or external circuits were connected by the
installer. [HAJDU product description](https://hajdurt.hu/termek/hajdu-pt-cf-erp/42),
[HAJDU buffer manual](https://hajdurt.hu/files/downloads/b00000093hpdf-20221129102935.pdf).

The **Honeywell VC4013-11** actuator is photographed on a three-port body marked
A/B/AB. It is a motorised hydronic routing valve. That does not establish a
thermostatic anti-scald mixer in the tap-water supply. Blue lever handles in the
photos are manual isolation valves. [Resideo VC actuator information](https://customer.resideo.com/en-US/Pages/quickview.aspx?IsDlg=1&pid=VC4013ZZ11%2FU).

The black four-port insulated unit with an air vent resembles a hydraulic
separator. Its model and internals have not been verified; it should not be
reported as a confirmed plate heat exchanger. The Wilo pump, Steca solar station,
Fernox TF1 filter and red expansion vessel are visible. Exact heating zones and
valve branch destinations need tracing.

The boiler's B3 reading is a store/DHW-control probe. It is not a measured tap
outlet temperature and cannot prove thermal treatment of the entire potable
coil, circulation loop or distribution pipework. A weekly 65°C proposal remains
disabled until the potable path and delivery-temperature protection are checked.

## Owner-traced controls

On 15 October 2026, the owner traced the tank temperature probe to the plain
green pair on the boiler's small terminal strip and confirmed it was returned
to its original tank sensor pocket. This is consistent with the B3 store input,
but the exact terminal numbering and tank-pocket height remain unverified.
The [Baxi manual, section 14](https://baxi.at/wp-content/uploads/2024/06/Luna-Platinum-1.pdf)
identifies M2 9–10 as the store-probe connection. Wire colour alone does not
identify a terminal function.

The photographed Delta S2302 RF receiver labels N/L as its mains supply and
1/2 as NO/COM relay contacts. The owner reports that this relay requests boiler
heat and switches the external heating pump's live; pump neutral is separate.
`control-map.svg` shows these functional relationships as reported connections,
not a certified electrical schematic. Pump identity, supply routing, protective
measures and the boiler contact terminals have not been electrically verified.
In the additional junction-box photos, the owner identifies the right cable as
the AC socket feed, the upper-left cable as the pump and the separate brown/blue
conductors as Delta relay leads. A blue relay conductor must not be assumed to
be neutral; its actual function depends on the traced circuit.
The receiver supplies an On/Off request, not the thermostat's measured room
temperature, over the traced contact connection.

A BSB-LAN thermostat-input override can change the boiler's interpreted heat
request. It cannot energise an external pump whose supply is interrupted by
the Delta relay. Do not label a boiler heat request as proof of pump operation
or radiator circulation. This map update changes no control automation.

## Native output and a possible external controller

A read-only device check on 15 October 2026 reported parameter 5890, relay QX1,
as **33 — Heat circuit pump HC1 Q2**. This is its configured function, not proof
of which physical pump is connected. The Baxi manual describes M3 6–7 as a
multifunction zone valve/pump relay contact, shared with other configurations.
It must be traced and its electrical suitability checked before any pump is
reassigned. No output, thermostat role or supply wiring was changed.

An external controller is another possible architecture, not installed here.
It would use suitable galvanically isolated thermostat inputs and properly
rated pump switching, with local interlocks, run-on and loss-of-communication
behavior. Existing mains-referenced Delta relay leads cannot be treated as
low-voltage GPIO contacts. [Raspberry Pi GPIO documentation](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#gpio)
specifies 3.3 V inputs. Home Assistant could supervise compatible Ethernet I/O
using [Modbus](https://www.home-assistant.io/integrations/modbus/) or MQTT while
the local controller handles immediate pump coordination. Native boiler burner
and temperature protections remain in charge; normal control must not rely on
cutting the boiler's mains supply.

For the Home Assistant map view, serve `system-map.svg` from
`/config/www/bsb-lan/system-map.svg`, reference `/local/bsb-lan/system-map.svg`, and
keep live boiler/store/return states separate from inferred component identities.
Serve `control-map.svg` beside it and show the owner-traced controls separately
from the untraced hydraulic routes.
