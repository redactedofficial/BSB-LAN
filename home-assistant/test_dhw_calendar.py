"""Exercise the shipped DHW templates and the actual imported timetable."""
import json
import ast
from datetime import datetime, timedelta
from pathlib import Path
import unittest
from zoneinfo import ZoneInfo

from jinja2.nativetypes import NativeEnvironment
import yaml

PACKAGE = yaml.safe_load(Path(__file__).with_name('dhw-calendar.yaml').read_text(encoding='utf-8'))
TZ = ZoneInfo('Europe/Budapest')

def timestamp(value, default=None):
    try:
        if isinstance(value, datetime):
            return value.timestamp()
        return datetime.fromisoformat(str(value)).timestamp()
    except (TypeError, ValueError):
        return default

def is_number(value):
    try:
        return float(value) == float(value)
    except (ValueError, TypeError):
        return False

def render(template, **values):
    env = NativeEnvironment()
    env.globals.update(as_timestamp=timestamp, is_number=is_number)
    result = env.from_string(template).render(**values)
    # HA trims rendered whitespace before parsing native scalar values.
    if isinstance(result, str):
        try:
            return ast.literal_eval(result.strip())
        except (ValueError, SyntaxError):
            return result.strip()
    return result

def all_nodes(value):
    yield value
    if isinstance(value, dict):
        for item in value.values():
            yield from all_nodes(item)
    elif isinstance(value, list):
        for item in value:
            yield from all_nodes(item)

class DHWCalendarTests(unittest.TestCase):
    def setUp(self):
        self.controller = PACKAGE['script']['bsb_dhw_calendar_reconcile']['sequence']
        self.window = next(n['variables']['window_end'] for n in self.controller
                           if 'variables' in n and 'window_end' in n['variables'])

    def active_end(self, now, events):
        return render(self.window, now=lambda: now,
                      calendar_result={'calendar.dhw_heating': {'events': events}})

    def events(self, day='2026-10-14'):
        return [{'start': f'{day}T06:00:00+02:00', 'end': f'{day}T07:30:00+02:00'},
                {'start': f'{day}T16:00:00+02:00', 'end': f'{day}T18:00:00+02:00'}]

    def test_exact_daily_boundaries(self):
        for hour, minute, active in [(5,59,False),(6,0,True),(7,0,True),(7,29,True),
                                     (7,30,False),(15,59,False),(16,0,True),
                                     (17,59,True),(18,0,False)]:
            with self.subTest(hour=hour, minute=minute):
                now = datetime(2026,10,14,hour,minute,tzinfo=TZ)
                self.assertEqual(self.active_end(now,self.events()) > now.timestamp(), active)

    def test_overlap_keeps_later_end(self):
        now = datetime(2026,10,14,7,0,tzinfo=TZ)
        events = self.events() + [{'start':'2026-10-14T07:00:00+02:00',
                                  'end':'2026-10-14T08:00:00+02:00'}]
        self.assertEqual(self.active_end(now,events), datetime(2026,10,14,8,tzinfo=TZ).timestamp())

    def test_empty_missing_and_all_day_are_off(self):
        now = datetime(2026,10,14,7,tzinfo=TZ)
        self.assertEqual(self.active_end(now,[]),0)
        self.assertEqual(self.active_end(now,[{'start':'2026-10-14','end':'2026-10-15'}]),0)
        self.assertEqual(render(self.window, now=lambda:now,calendar_result={}),0)

    def test_winter_time_stays_at_local_0600(self):
        now = datetime(2026,10,25,6,0,tzinfo=TZ)
        events = [{'start':'2026-10-25T06:00:00+01:00','end':'2026-10-25T07:30:00+01:00'}]
        self.assertEqual(self.active_end(now,events), datetime(2026,10,25,7,30,tzinfo=TZ).timestamp())

    def test_no_space_heating_or_thermostat_writes(self):
        for node in all_nodes(PACKAGE):
            if isinstance(node,dict) and node.get('action') == 'script.bsb_dhw_write_checked':
                self.assertIn(node['data']['parameter'],[1600,1610,1620])
        body=json.dumps(PACKAGE)
        for forbidden in ['5977','5978','742','700/set','heating_circuit_1']:
            self.assertNotIn(forbidden,body)
        writer=PACKAGE['script']['bsb_dhw_write_checked']['sequence'][0]['variables']['valid']
        for p,value,expected in [(1600,'0',True),(1600,'1',True),(1600,'2',False),
                                 (1620,'0',True),(1620,'2',False),(1610,'45',True),
                                 (1610,'80',False),(700,'1',False)]:
            self.assertEqual(render(writer,p=p,value=value),expected)

    def test_write_requires_fresh_precise_matching_reply(self):
        writer=PACKAGE['script']['bsb_dhw_write_checked']['sequence']
        ack=next(node['wait_template'] for node in writer if 'wait_template' in node)
        for arrival,payload,value,expected in [(100.49,'1 - On','1',False),
                                                (100.51,'1 - On','1',True),
                                                (100.51,'0 - Off','1',False),
                                                (100.51,'45.0','45',True),
                                                (100.51,'unknown','45',False)]:
            attrs={'received_at':arrival,'payload':payload}
            self.assertEqual(render(ack,state_attr=lambda entity,key:attrs.get(key),
                                    receipt='receipt',sent_at=100.50,value=value),expected)

    def test_enable_is_restored_and_stop_retry_is_persistent(self):
        self.assertNotIn('initial',PACKAGE['input_boolean']['bsb_dhw_calendar_enabled'])
        self.assertNotIn('initial',PACKAGE['input_boolean']['bsb_dhw_stop_pending'])
        may=next(n['variables']['may_heat'] for n in self.controller
                 if 'variables' in n and 'may_heat' in n['variables'])
        self.assertIn('bsb_dhw_stop_pending',may)
        self.assertIn('wait.completed',may)

if __name__ == '__main__':
    unittest.main()
