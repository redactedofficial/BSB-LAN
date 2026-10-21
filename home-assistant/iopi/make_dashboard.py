"""Native Home Assistant IO-PI dashboards; no command runs while opening a card."""
import json
from pathlib import Path
from iopi import PINS

root = Path(__file__).parent
prefix = 'bmsiopi'


def heading(title, icon):
    return {'type': 'heading', 'heading': title, 'icon': icon}


def section(cards):
    return {'type': 'grid', 'cards': cards}


def read_tile(entity, name, icon='mdi:chip'):
    return {'type': 'tile', 'entity': entity, 'name': name, 'icon': icon,
            'tap_action': {'action': 'more-info'}, 'icon_tap_action': {'action': 'none'},
            'grid_options': {'columns': 6, 'rows': 1}}


def action_button(name, script, icon, confirmation=None):
    action = {'action': 'perform-action', 'perform_action': 'script.' + script}
    if confirmation:
        action['confirmation'] = {'text': confirmation}
    return {'type': 'button', 'name': name, 'icon': icon, 'tap_action': action,
            'hold_action': {'action': 'none'}, 'grid_options': {'columns': 6, 'rows': 2}}


manual_buttons = [
    action_button('Pump only', 'iopi_pump_only_start', 'mdi:pump'),
    action_button("Fuck, it's so cold", 'bsb_manual_heat_start', 'mdi:fire',
                  'Run pump and request gas heat to the manual return cutoff (maximum one hour)? Calendars continue.'),
    action_button('Release pump hold', 'iopi_pump_override_release', 'mdi:autorenew'),
    action_button('End gas boost', 'bsb_manual_heat_stop', 'mdi:stop-circle-outline')]


heat_cards = [heading('Heating · BSB-LAN + IO-PI', 'mdi:radiator'),
    *manual_buttons,
    {'type': 'entities', 'show_header_toggle': False, 'entities': [
        {'entity': 'select.bmsiopi_heating_mode', 'name': 'Heating mode'},
        {'entity': 'input_boolean.bsb_calendar_enabled', 'name': 'Daily heating schedule'},
        {'entity': 'input_boolean.iopi_heating_blocked', 'name': 'Block automatic heating'},
        {'entity': 'input_boolean.bsb_heat_fault', 'name': 'Heating fault latch'},
        {'entity': 'switch.bmsiopi_pump_override', 'name': 'Manual pump hold'},
        {'entity': 'sensor.bmsiopi_buffer_water', 'name': 'Tank water · B3'},
        {'entity': 'input_boolean.iopi_prefer_stored_heat', 'name': 'Prefer stored solar heat'},
        {'entity': 'input_number.iopi_buffer_minimum', 'name': 'Use stored heat above'},
        {'entity': 'sensor.bmsiopi_daily_permission', 'name': 'Schedule permission'},
        {'entity': 'number.bmsiopi_return_cutoff', 'name': 'Manual return cutoff'},
        {'entity': 'sensor.bmsiopi_heating_status', 'name': 'Control status'},
        {'entity': 'sensor.bmsiopi_bsb_control', 'name': 'BSB-LAN request'},
        {'entity': 'sensor.bmsiopi_bsb_native_status', 'name': 'Actual boiler status'},
        {'entity': 'sensor.bmsiopi_return_water', 'name': 'Return water · BSB'},
        {'entity': 'sensor.bmsiopi_boiler_error', 'name': 'Boiler error · BSB'},
        {'entity': 'binary_sensor.bmsiopi_thermostat', 'name': 'Delta heat demand'}]},
    {'type': 'markdown', 'content': "**{{ states('sensor.bmsiopi_heating_status') }}**\n\n"
     "**Pump only** holds R2 on until released or communication is lost. It does not request gas or pause calendars. "
     "**Fuck, it's so cold** overrides room demand for a gas boost, bounded by the manual return cutoff and one hour. "
     "End gas boost returns control to the enabled schedule; an independent pump hold stays on.\n\n"
     "**Stored heat first:** with Delta demand, daytime circulation (06:00–22:00) can use tank heat between calendar slots. "
     "It starts at the selected tank temperature and releases 5°C below it. Gas fallback is confined to calendar/cold allowances. "
     "Warm weather and explicit automatic blocks still apply; manual controls remain independent. DHW has its own routine. "
     "{% if states('sensor.bmsiopi_return_water') in ['unknown','unavailable'] %}"
     "**Boiler feedback is unavailable; boiler charging is blocked. Allowed Delta demand can still circulate stored heat.**{% endif %}\n\n"
     "{% if states('binary_sensor.bmsiopi_thermostat') in ['unknown','unavailable'] %}"
     "**Delta input is not commissioned or unavailable.** {% endif %}"
     "GPIO26's raw level is not a heat-demand reading. "
     "Native boiler control still determines burner operation. "
     "The return cutoff needs BMS and BSB-LAN communication; a complete outage can prevent a software stop. "
     "[Building heating overview](/bms-overview/overview)"}]

relay_cards = [heading('Relay controls · R1–R8', 'mdi:electric-switch'),
    {'type': 'markdown', 'content': 'HIGH trigger · OFF = LOW GPIO drive. '
     'State is GPIO readback, without contact/load feedback. '
     'R3–R8 use five-minute leases. '
     'R1 is reserved OFF; boiler starts use BSB-LAN. R2 ON holds the pump; R2 OFF releases it to automatic control. '
     'Manual relay commands never pause calendars.'}]
for rid in range(1, 9):
    if rid == 1:
        relay_cards.append(read_tile('sensor.bmsiopi_gpio_17', 'R1 · Reserved off', 'mdi:electric-switch'))
        continue
    label = {2: 'R2 · Radiator pump'}.get(rid, f'Relay {rid}')
    relay_cards.append({'type': 'button', 'entity': f'switch.bmsiopi_relay_{rid}', 'name': label,
        'icon': 'mdi:radiator' if rid == 2 else 'mdi:fire' if rid == 1 else 'mdi:electric-switch',
        'show_state': True, 'tap_action': {'action': 'toggle', 'confirmation': {
            'text': f'Change {label}? This switches its connected circuit; pump run-on may delay OFF.'}},
        'hold_action': {'action': 'none'}, 'double_tap_action': {'action': 'none'},
        'grid_options': {'columns': 6, 'rows': 2}})

health_cards = [heading('IO-PI · System', 'mdi:raspberry-pi'),
    {'type': 'entities', 'show_header_toggle': False, 'entities': [
        {'entity': 'sensor.bmsiopi_status', 'name': 'I/O setup'},
        {'entity': 'sensor.bmsiopi_temperature', 'name': 'CPU temperature'},
        {'entity': 'sensor.bmsiopi_power', 'name': 'Power status'},
        {'entity': 'sensor.bmsiopi_uptime', 'name': 'Service uptime'}]},
    {'type': 'button', 'name': 'All usable GPIOs', 'icon': 'mdi:chip',
     'tap_action': {'action': 'navigate', 'navigation_path': '/dashboard-io-pi/gpio'}},
    {'type': 'markdown', 'content': 'MQTT connects over verified TLS. Missing or stale readings show unavailable. '
     'Only used pins have function names; the other GPIOs keep their numbers. '
     'The generic relay module has no electronic identity interface, so its physical presence is not detected.'}]

groups = []
names = {27: 'Radiator pump', 26: 'Delta input'}
for gpios in [list(range(2, 10)), list(range(10, 18)), list(range(18, 28))]:
    cards = [heading(f'GPIO {gpios[0]}–{gpios[-1]}', 'mdi:chip')]
    for gpio in gpios:
        label = f'GPIO {gpio} · P{PINS[gpio]}'
        if gpio in names:
            label = f'{names[gpio]} · GPIO {gpio}'
        tile = read_tile(f'sensor.bmsiopi_gpio_{gpio}', label)
        tile['state_content'] = ['state', 'mode']
        cards.append(tile)
    groups.append(section(cards))

dashboard = {'title': 'IO-PI', 'views': [
    {'title': 'Overview', 'path': 'overview', 'icon': 'mdi:raspberry-pi', 'type': 'sections', 'max_columns': 3,
     'header': {'card': {'type': 'markdown', 'content': '# IO-PI\nHeating I/O · Eight relays · Delta demand'}},
     'sections': [section(heat_cards), section(relay_cards), section(health_cards)]},
    {'title': 'GPIO', 'path': 'gpio', 'icon': 'mdi:chip', 'type': 'sections', 'max_columns': 3,
     'header': {'card': {'type': 'markdown', 'content': '# All usable GPIOs\n26 header GPIOs · Physical pin numbers are shown as P#\n\n'
       'Raw logic levels and current pin modes. Unconnected inputs may float. Tap a pin for its physical position and function. '
       'GPIO0/1 are reserved for HAT identification; power, ground and internal SoC pins are excluded.'}},
     'sections': groups}]}
(root / 'dashboard.json').write_text(json.dumps(dashboard, ensure_ascii=False, indent=2) + '\n', encoding='utf8')

integration = section([heading('IO-PI · Heating interface', 'mdi:raspberry-pi'),
    read_tile('binary_sensor.bmsiopi_boiler_request', 'Boiler request · BSB', 'mdi:fire'),
    read_tile('switch.bmsiopi_relay_2', 'Radiator pump · R2', 'mdi:radiator'),
    read_tile('binary_sensor.bmsiopi_thermostat', 'Delta demand', 'mdi:thermostat'),
    read_tile('sensor.bmsiopi_daily_permission', 'Daily permission', 'mdi:calendar-check'),
    read_tile('sensor.bmsiopi_bsb_native_status', 'Actual boiler', 'mdi:fire'),
    {'type': 'markdown', 'content': 'Delta can use stored tank heat during the day between slots. Gas fallback follows calendar/cold allowances. '
     'Pump only is an independent hold; manual controls never pause calendars. R1 stays off. DHW keeps its separate routine.'},
    {'type': 'button', 'name': 'Open IO-PI', 'icon': 'mdi:raspberry-pi',
     'tap_action': {'action': 'navigate', 'navigation_path': '/dashboard-io-pi/overview'}}])
(root / 'bms-section.json').write_text(json.dumps(integration, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
print('Prepared IO-PI overview, all 26 GPIOs and BMS heating link.')
