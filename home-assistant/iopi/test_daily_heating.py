"""Evaluate the installed HA package's actual schedule and weather templates."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import math
import unittest
import yaml
from jinja2.nativetypes import NativeEnvironment

PACKAGE = yaml.safe_load(Path(__file__).with_name('daily-heating.yaml').read_text(encoding='utf8'))
SEQUENCE = PACKAGE['script']['bsb_heat_control']['sequence']

class DailyTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 16, 6, 10, tzinfo=timezone(timedelta(hours=2)))
        self.state = {
            'calendar.heating': 'on', 'input_boolean.bsb_calendar_enabled': 'on',
            'input_boolean.bsb_weather_gate_enabled': 'on', 'input_boolean.bsb_cold_boost_enabled': 'on',
            'input_boolean.bsb_cold_boost_overnight': 'on', 'sensor.bsb_outdoor_weather_estimate': '8.5',
            'input_number.bsb_heating_weather_limit': '25', 'input_number.bsb_cold_boost_temperature': '0',
            'input_number.bsb_calendar_hot_target': '50', 'input_number.bsb_calendar_hysteresis': '2',
            'input_boolean.iopi_heating_blocked': 'off', 'input_boolean.bsb_heat_fault': 'off',
        }
        self.events = [{'start': '2026-10-16T06:00:00+02:00', 'end': '2026-10-16T06:30:00+02:00'}]
        self.env = NativeEnvironment()
        self.env.filters['to_json'] = json.dumps
        self.env.globals.update(now=lambda: self.now, timedelta=timedelta,
             states=lambda entity: self.state.get(entity, 'unknown'),
             is_state=lambda entity, value: self.state.get(entity) == value,
             is_number=lambda value: self.number(value), as_timestamp=self.timestamp)

    @staticmethod
    def number(value):
        try:
            return math.isfinite(float(value))
        except (TypeError, ValueError):
            return False

    @staticmethod
    def timestamp(value, default=0):
        try:
            if isinstance(value, (int, float)):
                return value
            return (value if isinstance(value, datetime) else datetime.fromisoformat(value)).timestamp()
        except (TypeError, ValueError):
            return default

    def decisions(self, result=None):
        values = {'operation': 'reconcile', 'calendar_result':
                  result if result is not None else {'calendar.heating': {'events': self.events}}}
        for step in SEQUENCE:
            for key, template in step.get('variables', {}).items():
                if key == 'calendar_result':
                    continue
                values[key] = self.env.from_string(template).render(**values)
        return values

    def test_all_templates_compile(self):
        def walk(value):
            if isinstance(value, dict):
                for child in value.values(): yield from walk(child)
            elif isinstance(value, list):
                for child in value: yield from walk(child)
            elif isinstance(value, str): yield value
        for text in walk(PACKAGE):
            self.env.from_string(text)

    def test_event_allows_permission_and_expires_at_end(self):
        self.assertTrue(self.decisions()['allowed'])
        self.now = self.now.replace(minute=29, second=40)
        self.assertEqual(self.decisions()['permission_expires'], self.timestamp(self.events[0]['end']))

    def test_event_end_and_all_day_event_do_not_heat(self):
        self.now = self.now.replace(minute=30)
        self.assertFalse(self.decisions()['allowed'])
        self.events = [{'start': '2026-10-16', 'end': '2026-10-17'}]
        self.assertFalse(self.decisions()['allowed'])

    def test_warm_and_unknown_weather_block(self):
        for value in ['25', '26', 'unknown', 'unavailable']:
            self.state['sensor.bsb_outdoor_weather_estimate'] = value
            self.assertFalse(self.decisions()['allowed'])

    def test_cold_weather_can_allow_overnight_but_still_respects_block(self):
        self.now = self.now.replace(hour=2)
        self.state['sensor.bsb_outdoor_weather_estimate'] = '0'
        self.assertTrue(self.decisions()['allowed'])
        self.state['input_boolean.iopi_heating_blocked'] = 'on'
        self.assertFalse(self.decisions()['allowed'])

    def test_overnight_permission_can_be_disabled(self):
        self.now = self.now.replace(hour=2)
        self.state['sensor.bsb_outdoor_weather_estimate'] = '-10'
        self.state['input_boolean.bsb_cold_boost_overnight'] = 'off'
        self.assertFalse(self.decisions()['allowed'])

    def test_disabled_or_faulted_or_missing_calendar_blocks(self):
        self.assertFalse(self.decisions(result={})['allowed'])
        for entity in ['input_boolean.iopi_heating_blocked', 'input_boolean.bsb_heat_fault']:
            self.state[entity] = 'on'
            self.assertFalse(self.decisions()['allowed'])
            self.state[entity] = 'off'
        self.state['input_boolean.bsb_calendar_enabled'] = 'off'
        self.assertFalse(self.decisions()['allowed'])

    def test_no_oem_parameter_writes_and_no_dhw_commands(self):
        text = json.dumps({'script': PACKAGE['script'], 'automation': PACKAGE['automation']})
        self.assertNotIn('BSB-LAN/', text)
        self.assertNotIn('select.select_option', text)
        self.assertNotIn('text.set_value', text.replace('input_text.set_value', ''))
        self.assertNotIn('bsb_dhw', text)

    def test_calendar_enablement_is_never_implicitly_changed(self):
        def walk(value):
            if isinstance(value, dict):
                yield value
                for child in value.values(): yield from walk(child)
            elif isinstance(value, list):
                for child in value: yield from walk(child)
        for step in walk({'script': PACKAGE['script'], 'automation': PACKAGE['automation']}):
            if step.get('action') in ('input_boolean.turn_on', 'input_boolean.turn_off', 'input_boolean.toggle'):
                self.assertNotEqual(step.get('target', {}).get('entity_id'), 'input_boolean.bsb_calendar_enabled')

    def test_explicit_stop_blocks_automatic_without_disabling_calendar(self):
        stop = SEQUENCE[1]['choose'][1]['sequence']
        self.assertEqual(stop[0]['action'], 'input_boolean.turn_on')
        self.assertEqual(stop[0]['target']['entity_id'], 'input_boolean.iopi_heating_blocked')
        self.assertEqual(stop[1]['data']['payload'], 'Off')

    def test_mode_completion_does_not_trigger_automatic_pause(self):
        pause = next(a for a in PACKAGE['automation'] if a['id']=='iopi_manual_control_pauses_daily_heating')
        self.assertEqual(pause['triggers'], [{'trigger':'mqtt','topic':'iopi/bmsiopi/heating/operator_action'}])
        template = pause['conditions'][0]['value_template']
        for action, age, expected in [('stop',0,True),('pump_manual',0,True),('stop',11,False),('completed',0,False)]:
            actual = self.env.from_string(template).render(trigger={'payload_json':{'action':action,'at':self.now.timestamp()-age}})
            self.assertEqual(actual, expected)

if __name__ == '__main__':
    unittest.main()
