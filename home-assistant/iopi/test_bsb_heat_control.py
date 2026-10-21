from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from bsb_heat_control import Controller, MqttIO, RequestEnded, decode_request


class IO:
    def __init__(self):
        self.values = {700: 3, 742: 50, 741: 80, 5977: 18, 5978: 1, 7865: 0,
                       6700: 0, 8314: 30, 8005: 25}
        self.writes, self.cancelled = [], False
        self.desired = {'active': True, 'mode': 'Manual', 'flow': 50, 'cutoff': 45}
        self.fail = None

    def number(self, p): return self.values[p]
    def text(self, p): return str(self.values[p])
    def request(self): return self.desired
    def cancel(self): self.cancelled = True
    def guard(self, expected):
        if not self.desired or not self.desired['active']:
            raise RuntimeError('Request expired')
        if self.values[6700] or self.values[8314] >= expected['cutoff']:
            raise RuntimeError('Fault or return cutoff')

    def set_checked(self, parameter, value):
        self.writes.append((parameter, value))
        if self.fail == (parameter, value):
            raise RuntimeError('Write unconfirmed')
        self.values[parameter] = value


class BsbTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'owned.json'
        self.io = IO()
        self.control = Controller(self.io, self.path)

    def test_fresh_request_is_bounded_and_consistent(self):
        valid = dict(self.io.desired, expires=105)
        self.assertTrue(decode_request(json.dumps(valid), 100)['active'])
        for change in [{'expires': 99}, {'expires': 121}, {'flow': 75},
                       {'flow': 51}, {'cutoff': float('nan')}, {'active': 'true'}, {'mode': 'Off'}]:
            with self.assertRaises(ValueError):
                decode_request(json.dumps(dict(valid, **change)), 100)

    def test_native_sequence_and_normal_stop_restore_owned_h5(self):
        self.control.step()
        self.assertEqual(self.io.writes, [(700, 0), (742, 50), (5978, 0), (700, 3)])
        self.assertTrue(self.path.exists())
        self.io.desired = None
        self.control.step()
        self.assertEqual(self.io.values[700], 0)
        self.assertEqual(self.io.values[5978], 1)
        self.assertFalse(self.path.exists())

    def test_normal_return_cutoff_restores_without_fault_pause(self):
        self.control.step()
        def ended(expected):
            raise RequestEnded('Return-water target reached')
        self.io.guard = ended
        self.control.step()
        self.assertFalse(self.io.cancelled)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.io.values[5978], 1)

    def test_mqtt_normal_shutdown_and_failure_publish_distinct_events(self):
        io = MqttIO.__new__(MqttIO)
        sent = []
        io.publish = lambda topic,payload: sent.append((topic,payload))
        io.cancel(fault=False)
        self.assertEqual(len(sent), 1)
        self.assertTrue(sent[0][0].endswith('/mode/set'))
        sent.clear()
        io.cancel()
        self.assertTrue(sent[0][0].endswith('/native_fault'))
        self.assertTrue(sent[1][0].endswith('/mode/set'))

    def test_physical_closed_contact_and_wrong_h5_role_are_rejected(self):
        for p, v in [(7865, 1), (5977, 0), (5978, 0), (741, 45)]:
            original = self.io.values[p]
            self.io.values[p] = v
            with self.assertRaises(RuntimeError): self.control.step()
            self.assertEqual(self.io.writes, [])
            self.assertTrue(self.io.cancelled)
            self.io.values[p] = original

    def test_cutoff_and_fault_cancel_and_restore(self):
        self.control.step()
        self.io.values[8314] = 45
        with self.assertRaises(RuntimeError): self.control.step()
        self.assertTrue(self.io.cancelled)
        self.control.release('cutoff')
        self.assertEqual(self.io.values[5978], 1)

    def test_unconfirmed_start_can_be_restored_after_crash(self):
        self.io.fail = (700, 3)
        with self.assertRaises(RuntimeError): self.control.step()
        self.assertTrue(self.path.exists())
        self.io.fail = None
        recovered = Controller(self.io, self.path)
        recovered.release('restart')
        self.assertEqual(self.io.values[700], 0)
        self.assertEqual(self.io.values[5978], 1)

    def test_failed_stop_keeps_recovery_journal(self):
        self.control.step()
        self.io.fail = (700, 0)
        with self.assertRaises(RuntimeError): self.control.release('stop')
        self.assertTrue(self.path.exists())

    def test_external_flow_change_is_preserved_on_stop(self):
        self.control.step()
        self.io.values[742] = 42
        self.control.release('operator change')
        self.assertEqual(self.io.values[742], 42)

    def test_hour_limit_is_not_renewed_by_repeated_requests(self):
        now = [1.0]
        self.control.clock = lambda: now[0]
        self.control.step()
        now[0] += 3600
        with self.assertRaises(RuntimeError): self.control.step()
        self.assertTrue(self.io.cancelled)


if __name__ == '__main__':
    unittest.main()
