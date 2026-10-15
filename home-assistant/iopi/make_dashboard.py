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


def mode_button(name, mode, icon):
    action = {'action': 'perform-action', 'perform_action': 'mqtt.publish',
              'data': {'topic': 'iopi/bmsiopi/heating/mode/set', 'payload': mode, 'retain': False}}
    if mode != 'Off':
        action['confirmation'] = {'text': f'{name}? This can start the radiator pump and request boiler heat.'}
    return {'type': 'button', 'name': name, 'icon': icon, 'tap_action': action,
            'hold_action': {'action': 'none'}, 'grid_options': {'columns': 6, 'rows': 2}}


heat_cards = [heading('Heating · IO-PI', 'mdi:radiator'),
    {'type': 'entities', 'show_header_toggle': False, 'entities': [
        {'entity': 'select.bmsiopi_heating_mode', 'name': 'Heating mode'},
        {'entity': 'number.bmsiopi_return_cutoff', 'name': 'Return-water cutoff'},
        {'entity': 'sensor.bmsiopi_heating_status', 'name': 'Control status'},
        {'entity': 'sensor.bmsiopi_return_water', 'name': 'Return water · BSB'},
        {'entity': 'sensor.bmsiopi_boiler_error', 'name': 'Boiler error · BSB'},
        {'entity': 'binary_sensor.bmsiopi_thermostat', 'name': 'Delta heat demand'}]},
    mode_button('Heat once', 'Manual', 'mdi:fire'),
    mode_button('Stop heating', 'Off', 'mdi:stop-circle-outline'),
    {'type': 'markdown', 'content': "**{{ states('sensor.bmsiopi_heating_status') }}**\n\n"
     "R1 requests boiler heat; R2 runs the radiator pump. Starts with five seconds of pump priming; "
     "stops at the return cutoff or one hour, then allows two minutes of pump run-on. "
     "Manual ignores room demand; Thermostat follows the Delta contact. "
     "Fresh boiler return/error feedback is required. "
     "{% if states('sensor.bmsiopi_return_water') in ['unknown','unavailable'] %}"
     "**Boiler feedback is unavailable; heat requests are blocked.**{% endif %}\n\n"
     "{% if states('binary_sensor.bmsiopi_thermostat') in ['unknown','unavailable'] %}"
     "**Delta input is not commissioned or unavailable.** {% endif %}"
     "GPIO26's raw level is not a heat-demand reading. "
     "Native boiler control still determines burner operation. "
     "[Building heating overview](/bms-overview/overview)"}]

relay_cards = [heading('Relay controls · R1–R8', 'mdi:electric-switch'),
    {'type': 'markdown', 'content': 'HIGH trigger · OFF = LOW GPIO drive. '
     'State is GPIO readback, without contact/load feedback. '
     'R3–R8 and independent pump operation use five-minute leases.'}]
for rid in range(1, 9):
    label = {1: 'R1 · Boiler request', 2: 'R2 · Radiator pump'}.get(rid, f'Relay {rid}')
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
names = {17: 'Boiler request', 27: 'Radiator pump', 26: 'Delta input'}
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
    read_tile('switch.bmsiopi_relay_1', 'Boiler request · R1', 'mdi:fire'),
    read_tile('switch.bmsiopi_relay_2', 'Radiator pump · R2', 'mdi:radiator'),
    read_tile('binary_sensor.bmsiopi_thermostat', 'Delta demand', 'mdi:thermostat'),
    read_tile('sensor.bmsiopi_heating_status', 'IO-PI control', 'mdi:information-outline'),
    {'type': 'markdown', 'content': 'R1/R2 are the relay interface. '
     'Missing boiler feedback blocks IO-PI heat. The existing BSB/DHW controls remain separate.'},
    {'type': 'button', 'name': 'Open IO-PI', 'icon': 'mdi:raspberry-pi',
     'tap_action': {'action': 'navigate', 'navigation_path': '/dashboard-io-pi/overview'}}])
(root / 'bms-section.json').write_text(json.dumps(integration, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
print('Prepared IO-PI overview, all 26 GPIOs and BMS heating link.')
