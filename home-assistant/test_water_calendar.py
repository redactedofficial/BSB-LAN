"""Evaluate the package's real Jinja decisions without publishing boiler commands."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import math
import os
import unittest
import yaml
from jinja2.nativetypes import NativeEnvironment

CONFIG = yaml.safe_load(Path(os.environ.get('BSB_HEAT_PACKAGE', Path(__file__).with_name('manual-return-heat.yaml'))).read_text(encoding='utf-8'))
NOW = datetime(2026, 10, 14, 0, 0, tzinfo=timezone.utc)
MODE = 'select.bsb_lan_00_09_heating_circuit_1_700_operating_mode'
H5 = 'select.bsb_lan_00_29_configuration_5978_type_of_contact_h5'
ROLE = 'select.bsb_lan_00_29_configuration_5977_input_h5_function_selection'
RAW = 'sensor.bsb_lan_00_33_io_test_7865_contact_state_h5'
ERROR = 'sensor.bsb_lan_00_31_error_6700_error_signal'
FLOW = 'text.bsb_lan_00_09_heating_circuit_1_742_flow_temp_setpoint_room_thermostat_hc1_degc'
RETURN = 'sensor.bsb_lan_00_36_diagnostics_producer_8314_return_temp_actual_value'
DEMAND = 'sensor.bsb_lan_00_37_diagnostics_consumer_8749_room_thermostat_heating_circuit_1'
READBACK = {MODE: 'sensor.bsb_heat_mode_readback', H5: 'sensor.bsb_heat_h5_readback',
            FLOW: 'sensor.bsb_heat_flow_readback', RETURN: 'sensor.bsb_heat_return_readback',
            ROLE: 'sensor.bsb_heat_role_readback', RAW: 'sensor.bsb_heat_contact_readback', ERROR: 'sensor.bsb_heat_error_readback'}

class State:
    def __init__(self, value, age=0):
        self.state = value
        self.last_reported = NOW - timedelta(seconds=age)

class States(dict):
    def __call__(self, entity):
        return self.get(entity, State('unknown')).state

def timestamp(value, default=0):
    try:
        if isinstance(value, (int, float)):
            return value
        return (value if isinstance(value, datetime) else datetime.fromisoformat(value)).timestamp()
    except (TypeError, ValueError):
        return default

def is_number(value):
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False

def walk(value):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)

class WaterCalendarTests(unittest.TestCase):
    def setUp(self):
        self.states = States({
            MODE: State('3 - Comfort'), H5: State('1 - normal opened'),
            ROLE: State('18 - Room thermostat HC1'), RAW: State('0'), ERROR: State('0 - 0:No error'),
            FLOW: State('35.0'), RETURN: State('40'), DEMAND: State('0 - No demand'),
            'input_boolean.bsb_manual_heat_active': State('off'),
            'input_boolean.bsb_thermostat_override': State('on'),
            'input_boolean.bsb_cycle_override': State('on'),
            'input_number.bsb_heat_flow_ceiling': State('55'),
            'input_number.bsb_cycle_flow_target': State('50'),
            'input_number.bsb_cycle_return_target': State('45'),
            'input_text.bsb_saved_flow': State('35.0'),
            'input_text.bsb_saved_h5': State('1 - normal opened'),
            'input_text.bsb_heat_owner': State('manual'),
            'input_text.bsb_cycle_h5': State('0 - normal closed'),
            'input_datetime.bsb_manual_heat_deadline': State((NOW + timedelta(hours=1)).isoformat()),
        })
        for entity, readback in READBACK.items():
            self.states[readback] = State(NOW.isoformat())
        self.payloads = {READBACK[entity]: self.states(entity) for entity in READBACK}
        self.env = NativeEnvironment()
        self.env.globals.update(states=self.states, now=lambda: NOW, timedelta=timedelta,
            as_timestamp=timestamp, is_number=is_number,
            state_attr=lambda entity, attr: '°C' if entity == RETURN and attr == 'unit_of_measurement' else self.payloads.get(entity) if attr == 'payload' else timestamp(self.states(entity)) if attr == 'received_at' else None,
            is_state=lambda entity, value: self.states(entity) == value)
        controller = CONFIG['script']['bsb_heat_control']['sequence'][0]
        self.start = controller['choose'][0]['sequence']
        self.stop = controller['default'][0]['choose'][0]['sequence']
        self.start_vars = next(x['variables'] for x in self.start if 'feedback_valid' in x.get('variables', {}))
        self.guard_vars = next(x['variables'] for x in CONFIG['automation'][0]['actions'] if 'external_change' in x.get('variables', {}))

    def render(self, text, **variables):
        return self.env.from_string(text).render(**variables)

    def test_all_templates_compile(self):
        for item in walk(CONFIG):
            if isinstance(item, str) and ('{{' in item or '{%' in item):
                self.env.from_string(item)

    def test_fresh_feedback_required(self):
        expr = self.start_vars['feedback_valid']
        self.assertTrue(self.render(expr))
        for entity in (RETURN, H5, FLOW):
            saved = self.states[entity]
            self.states[READBACK[entity]] = State((NOW - timedelta(seconds=181)).isoformat())
            self.assertFalse(self.render(expr))
            self.states[READBACK[entity]] = State(NOW.isoformat())
            self.states[entity] = State('unknown')
            self.assertFalse(self.render(expr))
            self.states[entity] = saved
        self.states[H5] = State('2 - Some other function')
        self.assertFalse(self.render(expr))

    def test_target_bounds_and_flow_headroom(self):
        condition = next(x['choose'][0]['conditions'] for x in self.start
            if 'exceeds configured flow ceiling' in str(x))
        self.assertFalse(self.render(condition, cutoff=45, requested_flow=50))
        self.assertFalse(self.render(condition, cutoff=50, requested_flow=55))
        self.assertTrue(self.render(condition, cutoff=51, requested_flow=56))
        self.assertTrue(self.render(condition, cutoff=40, requested_flow=45))
        self.assertTrue(self.render(condition, cutoff=0, requested_flow=5))

    def test_thermostat_gate_is_opt_in_override(self):
        condition = next(x['choose'][0]['conditions'] for x in self.start
            if 'override is off' in str(x))
        self.assertFalse(self.render(condition, use_override=True))
        self.states['input_boolean.bsb_thermostat_override'] = State('off')
        self.assertTrue(self.render(condition, use_override=False))
        self.states[DEMAND] = State('1 - Demand')
        self.states[RAW] = State('1')
        self.assertFalse(self.render(condition, use_override=False))

    def test_switching_off_override_releases_owned_cycle(self):
        self.states[H5] = State('0 - normal closed')
        self.states[FLOW] = State('50.0')
        self.assertFalse(self.render(self.guard_vars['external_change']))
        self.states['input_boolean.bsb_thermostat_override'] = State('off')
        self.assertTrue(self.render(self.guard_vars['external_change']))

    def test_cutoff_deadline_missing_feedback(self):
        self.assertFalse(self.render(self.guard_vars['stale']))
        self.assertFalse(self.render(self.guard_vars['deadline_passed']))
        self.states[READBACK[RETURN]] = State((NOW - timedelta(seconds=181)).isoformat())
        self.assertTrue(self.render(self.guard_vars['stale']))
        self.states['input_datetime.bsb_manual_heat_deadline'] = State('unknown')
        self.assertTrue(self.render(self.guard_vars['deadline_passed']))
        branch = next(x for x in walk(CONFIG['automation'][0]) if isinstance(x, dict)
            and 'conditions' in x and 'Return-water target reached' in str(x)
            and 'states(' in str(x['conditions']))
        self.states[RETURN] = State('45')
        self.assertTrue(self.render(branch['conditions'], cutoff=45))

    def test_external_setting_changes_release_control(self):
        self.states[H5] = State('0 - normal closed')
        self.states[FLOW] = State('50.0')
        expr = self.guard_vars['external_change']
        self.assertFalse(self.render(expr))
        self.states[FLOW] = State('52.0')
        self.assertTrue(self.render(expr))
        self.states[FLOW] = State('50.0')
        self.states[MODE] = State('1 - Automatic')
        self.assertTrue(self.render(expr))

    def test_only_owned_settings_are_restored(self):
        condition = next(x['choose'][0]['conditions'] for x in self.stop
            if 'h5_ack' in str(x))
        self.states[H5] = State('0 - normal closed')
        self.assertTrue(self.render(condition))
        self.states[H5] = State('1 - normal opened')
        self.assertFalse(self.render(condition))
        flow_condition = next(x['choose'][0]['conditions'] for x in self.stop if 'flow_ack' in str(x))
        self.states[FLOW] = State('50.0')
        self.assertTrue(self.render(flow_condition))
        self.states[FLOW] = State('52.0')
        self.assertFalse(self.render(flow_condition))

    def test_checked_write_allowlist_and_fresh_ack(self):
        sequence = CONFIG['script']['bsb_heat_write_checked']['sequence']
        valid = sequence[0]['variables']['valid_write']
        self.assertTrue(self.render(valid, entity=MODE, value='0 - Protection', kind='select'))
        self.assertTrue(self.render(valid, entity=H5, value='0 - normal closed', kind='select'))
        for entity, value, kind in [('select.relay', 'on', 'select'), (FLOW, 'nan', 'text'),
                                    (FLOW, '81', 'text'), (H5, '1 - Some other function', 'select')]:
            self.assertFalse(self.render(valid, entity=entity, value=value, kind=kind))
        ack = next(x['wait_template'] for x in sequence if 'wait_template' in x)
        self.assertFalse(self.render(ack, entity=MODE, readback=READBACK[MODE], value='3 - Comfort', kind='select', sent_at=NOW.timestamp()+1))
        self.assertTrue(self.render(ack, entity=MODE, readback=READBACK[MODE], value='3 - Comfort', kind='select', sent_at=NOW.timestamp()-1))
        self.payloads[READBACK[MODE]] = '3'
        self.assertFalse(self.render(ack, entity=MODE, readback=READBACK[MODE], value='3 - Comfort', kind='select', sent_at=NOW.timestamp()-1))

    def test_identical_values_can_be_fresh_receipts(self):
        for entity in (RETURN, H5, FLOW, MODE):
            self.states[entity] = State(self.states(entity), age=86400)
        self.assertTrue(self.render(self.start_vars['feedback_valid']))
        self.assertFalse(self.render(self.guard_vars['stale']))

    def test_faults_and_contact_changes(self):
        self.assertFalse(self.render(self.guard_vars['boiler_fault']))
        self.states[ERROR] = State('10 - 10:Outside sensor error')
        self.assertTrue(self.render(self.guard_vars['boiler_fault']))
        self.assertFalse(self.render(self.start_vars['feedback_valid']))
        self.states[ERROR] = State('0 - 0:No error')
        self.assertEqual(self.render(self.start_vars['forced_contact']), '0 - normal closed')
        self.states[RAW] = State('1')
        self.assertEqual(self.render(self.start_vars['forced_contact']), '1 - normal opened')
        # Thermostat role is preserved: no writable operation can target 5977.
        writes = [x for x in walk(CONFIG) if isinstance(x, dict) and x.get('action') == 'script.bsb_heat_write_checked']
        self.assertNotIn(ROLE, {x['data']['entity'] for x in writes})

    def test_journal_is_flushed_before_boiler_write(self):
        first_write = next(i for i, x in enumerate(self.start) if x.get('action') == 'script.bsb_heat_write_checked')
        flush = next(i for i, x in enumerate(self.start) if x.get('action') == 'homeassistant.save_persistent_states')
        self.assertLess(flush, first_write)

    def test_overlapping_calendar_windows_and_timezone(self):
        expr = next(x['variables']['event_window_active'] for x in CONFIG['automation'][1]['actions']
                    if 'event_window_active' in x.get('variables', {}))
        def active(events):
            return self.render(expr, calendar_result={'calendar.heating': {'events': events}})
        self.assertFalse(active([]))
        self.assertFalse(active([SimpleNamespace(start='2026-10-13T22:00:00+02:00', end='2026-10-14T02:00:00+02:00')]))
        self.assertTrue(active([
            SimpleNamespace(start='2026-10-13T22:00:00+02:00', end='2026-10-14T02:00:00+02:00'),
            SimpleNamespace(start='2026-10-14T01:30:00+02:00', end='2026-10-14T03:00:00+02:00')]))

    def test_calendar_deadline_is_bounded_by_event_end(self):
        expr = next(x['data']['timestamp'] for x in self.start
                    if x.get('action') == 'input_datetime.set_datetime')
        self.states['input_number.bsb_manual_heat_max_minutes'] = State('60')
        half_hour = NOW.timestamp() + 1800
        self.assertEqual(self.render(expr, source='calendar', end_at=half_hour),half_hour)
        self.assertEqual(self.render(expr, source='calendar', end_at=NOW.timestamp()+7200),NOW.timestamp()+3600)
        self.assertEqual(self.render(expr, source='manual'),NOW.timestamp()+3600)

    def test_calendar_gaps_stop_and_never_start(self):
        actions = CONFIG['automation'][1]['actions']
        gap = next(node['choose'][0] for node in actions if 'choose' in node
                   and node['choose'][0]['conditions'] == '{{ not window_active or weather_blocked }}')
        self.assertTrue(self.render(gap['conditions'],window_active=False,weather_blocked=False))
        self.assertFalse(self.render(gap['conditions'],window_active=True,weather_blocked=False))
        self.assertTrue(self.render(gap['conditions'],window_active=True,weather_blocked=True))
        body=str(gap['sequence'])
        self.assertIn('Heating event ended',body)
        self.assertIn('0 - Protection',body)
        self.assertNotIn("'operation': 'start'",body)
        start = next(x for x in actions if x.get('action') == 'script.bsb_heat_control')
        self.assertEqual(start['data']['end_at'],'{{ window_end }}')

    def test_optional_weather_gate_preserves_schedule_when_disabled(self):
        expr = next(node['variables']['weather_blocked'] for node in CONFIG['automation'][1]['actions']
                    if 'weather_blocked' in node.get('variables',{}))
        gate='input_boolean.bsb_weather_gate_enabled'
        outside='sensor.bsb_outdoor_weather_estimate'
        self.states[gate]=State('off')
        self.states[outside]=State('unknown')
        self.states['input_number.bsb_heating_weather_limit']=State('18')
        self.assertFalse(self.render(expr))
        self.states[gate]=State('on')
        self.assertTrue(self.render(expr))
        for temp,blocked in [('17.9',False),('18',True),('25',True),('unavailable',True)]:
            self.states[outside]=State(temp)
            self.assertEqual(self.render(expr),blocked)

    def test_calendar_and_cold_boost_respect_thermostat(self):
        expr=self.start_vars['use_override']
        self.assertTrue(self.render(expr,source='manual'))
        self.assertFalse(self.render(expr,source='calendar'))
        self.states['input_text.bsb_heat_owner']=State('calendar')
        self.states['input_boolean.bsb_cycle_override']=State('off')
        self.states[H5]=State('0 - normal closed')
        self.states[FLOW]=State('50')
        self.assertFalse(self.render(self.guard_vars['external_change']))

    def test_cold_boost_threshold_and_overnight_permission(self):
        expr=next(x['variables']['cold_boost'] for x in CONFIG['automation'][1]['actions']
                  if 'cold_boost' in x.get('variables',{}))
        for entity in ['input_boolean.bsb_weather_gate_enabled','input_boolean.bsb_cold_boost_enabled']:
            self.states[entity]=State('on')
        self.states['input_number.bsb_cold_boost_temperature']=State('0')
        self.states['sensor.bsb_outdoor_weather_estimate']=State('-1')
        self.states['input_boolean.bsb_cold_boost_overnight']=State('off')
        self.assertFalse(self.render(expr))
        self.states['input_boolean.bsb_cold_boost_overnight']=State('on')
        self.assertTrue(self.render(expr))
        self.states['sensor.bsb_outdoor_weather_estimate']=State('0.1')
        self.assertFalse(self.render(expr))
        self.states['sensor.bsb_outdoor_weather_estimate']=State('unknown')
        self.assertFalse(self.render(expr))

    def test_journal_before_writes_and_no_retained_commands(self):
        journal = next(i for i, x in enumerate(self.start) if x.get('action') == 'input_boolean.turn_on')
        first_write = next(i for i, x in enumerate(self.start) if x.get('action') == 'script.bsb_heat_write_checked')
        self.assertLess(journal, first_write)
        for item in walk(CONFIG):
            if isinstance(item, dict) and item.get('action') == 'mqtt.publish':
                self.assertTrue(item['data']['topic'].endswith('/poll'))
                self.assertFalse(item['data']['retain'])
        self.assertFalse(CONFIG['input_boolean']['bsb_calendar_enabled']['initial'])
        self.assertEqual(CONFIG['script']['bsb_heat_control']['mode'], 'queued')

if __name__ == '__main__':
    unittest.main(verbosity=2)
