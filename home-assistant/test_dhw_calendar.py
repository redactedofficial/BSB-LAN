"""Exercise the shipped DHW templates and the actual imported timetable."""
import json
import ast
from datetime import datetime, timedelta
from pathlib import Path
import unittest
from zoneinfo import ZoneInfo
from types import SimpleNamespace

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

    def topup_templates(self):
        return {key: value for node in self.controller for key, value in node.get('variables', {}).items()}

    def context(self, **changes):
        states = {
            'input_boolean.bsb_dhw_calendar_enabled': 'on',
            'input_boolean.bsb_dhw_topup_enabled': 'on',
            'input_boolean.bsb_dhw_topup_active': 'off',
            'input_boolean.bsb_dhw_stop_pending': 'off',
            'input_text.bsb_dhw_topup_last_slot': '100',
            'input_number.bsb_dhw_topup_cycle_target': '45',
            'input_number.bsb_dhw_calendar_target': '45',
        }
        states.update(changes.pop('entity_states', {}))
        context = dict(check_topup=True, stopping=False, recovering=False,
            main_window_active=False, calendar_ok=True, feedback_ok=True,
            temperature_ok=True, actual_temperature=42.9, target_temperature=45,
            hour_slot='101', topup_opportunity=True,
            is_state=lambda entity, value: states.get(entity) == value,
            states=lambda entity: states.get(entity, 'unknown'))
        context.update(changes)
        return context

    def test_hourly_opportunity_never_duplicates_or_overlaps_main_period(self):
        template=self.topup_templates()['topup_opportunity']
        self.assertTrue(render(template,**self.context()))
        for override in [dict(check_topup=False),dict(stopping=True),dict(recovering=True),
                         dict(main_window_active=True),dict(hour_slot='100'),
                         dict(entity_states={'input_boolean.bsb_dhw_topup_active':'on'}),
                         dict(entity_states={'input_boolean.bsb_dhw_calendar_enabled':'off'}),
                         dict(entity_states={'input_boolean.bsb_dhw_topup_enabled':'off'})]:
            with self.subTest(override=override):
                self.assertFalse(render(template,**self.context(**override)))

    def test_two_degree_start_margin_and_invalid_feedback(self):
        template=self.topup_templates()['topup_may_start']
        for temperature,expected in [(42.9,True),(43.0,False),(44.9,False),(45,False),(50,False)]:
            self.assertEqual(render(template,**self.context(actual_temperature=temperature)),expected)
        for override in [dict(calendar_ok=False),dict(feedback_ok=False),dict(temperature_ok=False),
                         dict(topup_opportunity=False),dict(target_temperature=0),dict(target_temperature=80),
                         dict(entity_states={'input_boolean.bsb_dhw_stop_pending':'on'})]:
            self.assertFalse(render(template,**self.context(**override)))

    def test_reached_target_stale_sensor_error_and_target_change_end_topup(self):
        template=self.topup_templates()['topup_should_end']
        active={'input_boolean.bsb_dhw_topup_active':'on'}
        self.assertFalse(render(template,**self.context(entity_states=active)))
        for override in [dict(actual_temperature=45),dict(actual_temperature=46),
                         dict(temperature_ok=False),dict(feedback_ok=False),dict(calendar_ok=False),
                         dict(target_temperature=46),dict(target_temperature=0),
                         dict(main_window_active=True)]:
            self.assertTrue(render(template,**self.context(entity_states=active,**override)))

    def test_temperature_must_be_new_numeric_and_plausible(self):
        template=self.topup_templates()['temperature_ok']
        for arrival,payload,expected in [(100.49,'42',False),(100.51,'42',True),
                                        (100.51,'---',False),(100.51,'unknown',False),
                                        (100.51,'nan',False),(100.51,'inf',False),
                                        (100.51,'-2',False),(100.51,'101',False)]:
            self.assertEqual(render(template,read_at=100.5,temperature_raw=payload,
                state_attr=lambda entity,key:arrival if key=='received_at' else payload),expected)

    def test_deadline_is_five_minutes_journalled_before_native_on(self):
        nodes=list(all_nodes(self.controller))
        deadline=next(n for n in nodes if isinstance(n,dict) and n.get('action')=='input_datetime.set_datetime')
        now=datetime(2026,10,14,12,tzinfo=TZ)
        self.assertEqual(render(deadline['data']['timestamp'],now=lambda:now),now.timestamp()+300)
        opportunity=next(n for n in self.controller if n.get('if')=='{{ topup_opportunity }}')['then']
        self.assertEqual(opportunity[-1]['action'],'homeassistant.save_persistent_states')
        start_index=next(i for i,n in enumerate(self.controller) if n.get('if')=='{{ topup_opportunity }}')
        heat_index=next(i for i,n in enumerate(self.controller) if n.get('if')=='{{ may_heat }}')
        self.assertLess(start_index,heat_index)
        self.assertNotIn('initial',PACKAGE['input_boolean']['bsb_dhw_topup_active'])
        self.assertTrue(PACKAGE['input_boolean']['bsb_dhw_topup_recovery_pending']['initial'])

    def test_timeout_pause_restart_and_stop_retry_happen_before_poll_wait(self):
        early=next(n for n in self.controller if 'then' in n and any(
            isinstance(c,dict) and c.get('action')=='script.bsb_dhw_finish_topup' for c in n['then']))
        now=datetime(2026,10,14,12,tzinfo=TZ)
        active={'input_boolean.bsb_dhw_topup_active':'on'}
        def evaluate(**values):
            context=self.context(entity_states=active,**values)
            context.update(now=lambda:now,state_attr=lambda entity,key:now.timestamp()+300)
            return render(early['if'],**context)
        self.assertFalse(evaluate())
        self.assertTrue(evaluate(stopping=True))
        self.assertTrue(evaluate(recovering=True))
        context=self.context(entity_states=active,now=lambda:now,
                            state_attr=lambda entity,key:now.timestamp())
        self.assertTrue(render(early['if'],**context))
        self.assertLess(self.controller.index(early),next(i for i,n in enumerate(self.controller) if 'wait_template' in n))

    def test_unconfirmed_off_preserves_owned_cycle_for_retry(self):
        finish=PACKAGE['script']['bsb_dhw_finish_topup']['sequence']
        decision=next(n for n in finish if 'if' in n)
        successful=json.dumps(decision['then'])
        failed=json.dumps(decision['else'])
        self.assertIn('bsb_dhw_topup_active',successful)
        self.assertIn('input_boolean.turn_off',successful)
        self.assertNotIn('input_boolean.turn_off',failed)
        self.assertIn('persistent_notification.create',failed)
        self.assertEqual(finish[0]['target']['entity_id'],'input_boolean.bsb_dhw_stop_pending')

    def test_hourly_deadline_and_active_guard_are_wired(self):
        triggers=PACKAGE['automation'][0]['triggers']
        self.assertIn({'trigger':'time_pattern','minutes':'0','seconds':'0','id':'hourly'},triggers)
        self.assertIn({'trigger':'time','at':'input_datetime.bsb_dhw_topup_deadline','id':'deadline'},triggers)
        guard=PACKAGE['automation'][1]
        self.assertEqual(guard['conditions'][0]['entity_id'],'input_boolean.bsb_dhw_topup_active')
        self.assertEqual(guard['triggers'][0]['seconds'],'/10')
        data=PACKAGE['automation'][0]['actions'][0]['data']
        self.assertTrue(render(data['recover'],trigger=SimpleNamespace(platform='homeassistant')))
        self.assertFalse(render(data['hourly_check'],trigger=SimpleNamespace(id='deadline')))
        self.assertTrue(render(data['hourly_check'],trigger=SimpleNamespace(id='hourly')))

    def test_late_poll_completion_still_reports_a_timeout(self):
        owned=next(n for n in self.controller if n.get('if')=="{{ is_state('input_boolean.bsb_dhw_topup_active', 'on') }}")
        reason=owned['then'][0]['data']['reason']
        now=datetime(2026,10,14,12,tzinfo=TZ)
        for offset,timed_out in [(-1,True),(0,True),(1,False)]:
            value=render(reason,now=lambda:now,
                         state_attr=lambda entity,key:now.timestamp()+offset)
            self.assertEqual('Five-minute limit reached' in value,timed_out)

    def test_pause_target_change_and_deadline_rechecked_before_on(self):
        heat=next(n for n in self.controller if n.get('if')=='{{ may_heat }}')['then']
        final=next(n for n in heat if 'window_end' in n.get('if',''))['if']
        now=datetime(2026,10,14,12,tzinfo=TZ)
        context=self.context(now=lambda:now,window_end=now.timestamp()+1)
        self.assertTrue(render(final,**context))
        for override in [dict(window_end=now.timestamp()),
                         dict(entity_states={'input_boolean.bsb_dhw_calendar_enabled':'off'}),
                         dict(entity_states={'input_boolean.bsb_dhw_topup_enabled':'off'}),
                         dict(entity_states={'input_boolean.bsb_dhw_topup_recovery_pending':'on'}),
                         dict(entity_states={'input_number.bsb_dhw_calendar_target':'46'})]:
            self.assertFalse(render(final,**self.context(now=lambda:now,
                window_end=override.pop('window_end',now.timestamp()+1),**override)))

if __name__ == '__main__':
    unittest.main()
