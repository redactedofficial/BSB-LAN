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

For the Home Assistant map view, serve `system-map.svg` from
`/config/www/bsb-lan/system-map.svg`, reference `/local/bsb-lan/system-map.svg`, and
keep live boiler/store/return states separate from inferred component identities.
