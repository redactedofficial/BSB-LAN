from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
import queue
import threading

from iopi import PINS, RELAY_GPIO, GpioHardware, Heater, Node, Outputs, discovery, parse_pins, validate


def config(enabled=True):
    result = json.loads(Path(__file__).with_name('config.example.json').read_text())
    for relay in result['relays']:
        relay.update(enabled=enabled, active_low=False if enabled else None)
    return result


class Clock:
    now = 10.0
    def __call__(self):
        return self.now


class Hardware:
    def __init__(self):
        self.writes = []
    def set(self, rid, on):
        self.writes.append((rid, on))


class Tests(unittest.TestCase):
    def setUp(self):
        self.config, self.hw, self.clock = config(), Hardware(), Clock()
        self.outputs = Outputs(self.config, self.hw, self.clock)
        self.heater = Heater(self.config, self.outputs, self.clock, self.clock)

    def daily(self, allowed=True, target=45):
        self.config['thermostat'].update(enabled=True, connected=True)
        self.assertEqual(self.heater.daily_policy(json.dumps({'allowed': allowed, 'target': target,
                        'expires': self.clock.now + 75, 'reason': 'Calendar event' if allowed else 'Between events'})), 'accepted')
        self.assertEqual(self.heater.select('Thermostat'), 'accepted')

    def fresh(self, temp='40', error='0 - No error'):
        self.heater.feedback('return', temp)
        self.heater.feedback('error', error)

    def start(self):
        self.fresh()
        self.assertEqual(self.heater.select('Manual'), 'accepted')
        self.heater.tick(None)
        self.clock.now += 5
        self.heater.tick(None)

    def test_all_usable_header_gpio_unique_physical_pins(self):
        self.assertEqual(set(PINS), set(range(2, 28)))
        self.assertEqual(len(set(PINS.values())), 26)
        self.assertEqual(PINS[26], 37)
        self.assertEqual(PINS[17], 11)
        self.assertEqual(PINS[27], 13)

    def test_disabled_profile_does_not_claim_any_gpio(self):
        hw = GpioHardware(config(False))  # Works on Windows without GPIO libraries.
        self.assertEqual(hw.outputs, {})
        self.assertIsNone(hw.thermostat())
        hw.close()

    def test_validation_rejects_unknown_polarity_and_mapping(self):
        for change in [lambda c: c['relays'][0].update(active_low=None),
                       lambda c: c['relays'][0].update(gpio=2),
                       lambda c: c['relays'][1].update(enabled=False),
                       lambda c: c.update(lease_seconds=float('nan'))]:
            c = config()
            change(c)
            with self.assertRaises(ValueError):
                validate(c)

    def test_pin_parser_preserves_input_alternate_and_unknown(self):
        rows = [f'{g}: ip -- | lo // GPIO{g} = input' for g in PINS]
        rows[0] = '2: a0 -- | hi // GPIO2 = SDA1'
        rows[1] = '3: ip -- | -- // GPIO3 = input'
        result = parse_pins('\n'.join(rows))
        self.assertEqual(result[2]['mode'], 'Alternate')
        self.assertEqual(result[2]['level'], 'High')
        self.assertEqual(result[3]['level'], 'Unknown')
        with self.assertRaises(ValueError):
            parse_pins('\n'.join(rows[:-1]))

    def test_discovery_covers_26_gpio_8_relays_and_no_invented_labels(self):
        rows = dict(discovery(self.config))
        self.assertEqual(sum('/gpio_' in t for t in rows), 26)
        self.assertEqual(sum('/switch/' in t for t in rows), 8)
        self.assertEqual(len({r['unique_id'] for r in rows.values()}), len(rows))
        self.assertEqual(rows['homeassistant/sensor/bmsiopi/gpio_4/config']['name'], 'GPIO 4')
        self.assertIn('Boiler request', rows['homeassistant/switch/bmsiopi/relay_1/config']['name'])
        self.assertEqual(rows['homeassistant/switch/bmsiopi/relay_3/config']['name'], 'Relay 3')

    def test_uncommissioned_commands_never_write(self):
        outputs = Outputs(config(False), self.hw, self.clock)
        self.assertEqual(outputs.command(1, True), 'not_commissioned')
        self.assertEqual(self.hw.writes, [])

    def test_missing_or_invalid_feedback_blocks_boiler(self):
        for temp, error in [('nan', '0'), ('40', 'bad'), ('40', '118 - Low pressure')]:
            self.fresh(temp, error)
            self.assertEqual(self.heater.select('Manual'), 'blocked')
            self.heater.tick(None)
            self.assertEqual(self.hw.writes, [])

    def test_disconnected_delta_cannot_start_thermostat_mode(self):
        self.fresh()
        self.assertEqual(self.heater.select('Thermostat'), 'blocked')
        self.assertEqual(self.heater.result, 'Delta input not connected')

    def test_manual_mode_primes_pump_before_boiler(self):
        self.fresh()
        self.heater.select('Manual')
        self.heater.tick(None)
        self.assertEqual(self.hw.writes, [(2, True)])
        self.clock.now += 5
        self.heater.tick(None)
        self.assertEqual(self.hw.writes, [(2, True), (1, True)])

    def test_bsb_transport_never_energises_physical_boiler_relay(self):
        self.config['boiler_control'] = 'bsb_lan'
        validate(self.config)
        self.start()
        self.assertTrue(self.outputs.state[1])  # Logical request for BMS.
        self.assertEqual(self.hw.writes, [(2, True)])
        self.heater.stop()
        self.clock.now += 121
        self.outputs.tick()
        self.assertEqual(self.hw.writes, [(2, True), (2, False)])

    def test_stop_releases_boiler_before_pump_run_on(self):
        self.start()
        self.heater.stop()
        self.assertEqual(self.hw.writes[-1], (1, False))
        self.assertTrue(self.outputs.state[2])
        self.clock.now += 120
        self.outputs.tick()
        self.assertEqual(self.hw.writes[-1], (2, False))

    def test_stale_feedback_stops_heat(self):
        self.start()
        self.clock.now += 46
        self.heater.tick(None)
        self.assertEqual(self.heater.mode, 'Off')
        self.assertFalse(self.outputs.state[1])
        self.assertTrue(self.outputs.state[2])

    def test_cutoff_stops_heat(self):
        self.start()
        self.fresh('45')
        self.heater.tick(None)
        self.assertFalse(self.outputs.state[1])
        self.assertEqual(self.heater.result, 'Return-water target reached')

    def test_duplicate_start_does_not_extend_deadline(self):
        self.start()
        deadline = self.heater.deadline
        self.clock.now += 10
        self.fresh()
        self.heater.select('Manual')
        self.assertEqual(self.heater.deadline, deadline)

    def test_mqtt_disconnect_stops_all_and_drains_pump(self):
        self.start()
        self.outputs.command(3, True)
        self.outputs.disconnect()
        self.assertFalse(self.outputs.state[1])
        self.assertFalse(self.outputs.state[3])
        self.assertTrue(self.outputs.state[2])
        self.clock.now += 121
        self.outputs.tick()
        self.assertFalse(self.outputs.state[2])

    def test_generic_output_lease_expires(self):
        self.outputs.command(8, True)
        self.clock.now += 301
        self.outputs.tick()
        self.assertFalse(self.outputs.state[8])

    def test_thermostat_open_stops_heat_but_keeps_listening(self):
        self.daily()
        self.fresh()
        self.heater.tick(True)
        self.clock.now += 5
        self.heater.tick(True)
        self.assertTrue(self.outputs.state[1])
        self.heater.tick(False)
        self.assertEqual(self.heater.mode, 'Thermostat')
        self.assertFalse(self.outputs.state[1])

    def test_daily_closed_delta_with_hot_buffer_runs_pump_without_boiler(self):
        self.daily()
        self.fresh('50')
        self.heater.tick(True)
        self.assertTrue(self.outputs.state[2])
        self.assertFalse(self.outputs.state[1])

    def test_daily_can_use_stored_heat_when_boiler_feedback_is_missing(self):
        self.daily()
        self.heater.tick(True)
        self.assertTrue(self.outputs.state[2])
        self.assertFalse(self.outputs.state[1])

    def test_daily_blocked_or_expired_permission_never_starts_pump(self):
        self.daily(False)
        self.heater.tick(True)
        self.assertEqual(self.hw.writes, [])
        self.daily()
        self.clock.now += 76
        self.heater.tick(True)
        self.assertEqual(self.hw.writes, [])

    def test_daily_allowed_without_delta_demand_never_starts_any_heat(self):
        self.daily()
        self.fresh('30')
        self.heater.tick(False)
        self.heater.tick(None)
        self.assertEqual(self.hw.writes, [])

    def test_daily_boiler_error_blocks_both_outputs(self):
        self.daily()
        self.fresh('30', '118 - Low pressure')
        self.heater.tick(True)
        self.assertEqual(self.hw.writes, [])

    def test_daily_permission_expiry_stops_boiler_and_allows_pump_run_on(self):
        self.daily()
        self.fresh()
        self.heater.tick(True)
        self.clock.now += 5
        self.heater.tick(True)
        self.assertTrue(self.outputs.state[1])
        self.clock.now += 76
        self.heater.tick(True)
        self.assertFalse(self.outputs.state[1])
        self.assertTrue(self.outputs.state[2])
        self.clock.now += 121
        self.outputs.tick()
        self.assertFalse(self.outputs.state[2])

    def test_daily_stale_boiler_feedback_stops_request_but_can_circulate(self):
        self.daily()
        self.fresh()
        self.heater.tick(True)
        self.clock.now += 5
        self.heater.tick(True)
        self.clock.now += 46
        self.heater.tick(True)
        self.assertFalse(self.outputs.state[1])
        self.assertTrue(self.outputs.state[2])

    def test_invalid_and_outdated_policy_cannot_enable_heat(self):
        for changes in [{'expires': 9}, {'expires': 101}, {'target': 75}, {'allowed': 'true'}, {'target': float('nan')}]:
            policy = {'allowed': True, 'target': 45, 'expires': 85, 'reason': 'Event'}
            policy.update(changes)
            self.assertEqual(self.heater.daily_policy(json.dumps(policy)), 'invalid_policy')
            self.assertIsNone(self.heater.permission)

    def test_daily_charge_deadline_is_not_extended_by_policy_renewals(self):
        self.daily()
        self.fresh()
        self.heater.tick(True)
        self.clock.now += 5
        self.heater.tick(True)
        deadline = self.heater.charge_deadline
        self.clock.now += 10
        self.daily()
        self.fresh()
        self.heater.tick(True)
        self.assertEqual(self.heater.charge_deadline, deadline)

    def test_daily_target_stops_boiler_but_keeps_house_pump_running(self):
        self.daily()
        self.fresh()
        self.heater.tick(True)
        self.clock.now += 5
        self.heater.tick(True)
        self.fresh('45')
        self.heater.tick(True)
        self.assertFalse(self.outputs.state[1])
        self.assertTrue(self.outputs.state[2])

    def test_daily_pump_can_continue_with_fresh_permission_without_lease_chatter(self):
        self.daily()
        self.fresh('50')
        self.heater.tick(True)
        self.clock.now += 3601
        self.daily()
        self.fresh('50')
        self.heater.tick(True)
        self.outputs.tick()
        self.assertEqual(self.hw.writes, [(2, True)])

    def test_feedback_subscription_accepts_new_retained_publications_but_no_snapshot(self):
        subscriptions = {}
        client = SimpleNamespace(subscribe=lambda topic, **kwargs: subscriptions.update({topic: kwargs}))
        node = Node.__new__(Node)
        node.module = SimpleNamespace(SubscribeOptions=lambda **kwargs: kwargs)
        node.config, node.generation, node.connected = self.config, 0, threading.Event()
        node.on_connect(client, None, None, SimpleNamespace(is_failure=False), None)
        for topic in ('BSB-LAN/0/36/8314/status', 'BSB-LAN/0/31/6700/status'):
            self.assertFalse(subscriptions[topic]['options']['retainAsPublished'])
            self.assertEqual(subscriptions[topic]['options']['retainHandling'], 2)
        self.assertTrue(subscriptions['iopi/bmsiopi/relay_1/set']['options']['retainAsPublished'])

    def test_emergency_fault_latches_and_blocks_restart(self):
        self.start()
        self.outputs.emergency()
        self.assertTrue(self.outputs.fault)
        self.assertEqual(self.outputs.command(3, True), 'gpio_fault')
        self.assertEqual(self.heater.select('Manual'), 'blocked')

    def test_retained_and_duplicate_commands_never_enter_queue(self):
        node = Node.__new__(Node)
        node.events, node.generation = queue.Queue(maxsize=64), 1
        for retained, duplicate in [(True, False), (False, True)]:
            node.on_message(None, None, SimpleNamespace(topic='iopi/bmsiopi/relay_1/set',
                            payload=b'ON', retain=retained, dup=duplicate))
        self.assertTrue(node.events.empty())
        node.on_message(None, None, SimpleNamespace(topic='iopi/bmsiopi/relay_3/set',
                        payload=b'ON', retain=False, dup=False))
        self.assertEqual(node.events.get_nowait()[3:], (3, True))

    def test_retained_boiler_feedback_cannot_become_fresh(self):
        node = Node.__new__(Node)
        node.events, node.generation = queue.Queue(maxsize=64), 1
        node.on_message(None, None, SimpleNamespace(topic='BSB-LAN/0/36/8314/status',
                        payload=b'40', retain=True, dup=False))
        self.assertTrue(node.events.empty())

    def test_out_of_range_cutoff_configuration_rejected(self):
        c = config()
        c['return_cutoff'] = 75
        with self.assertRaises(ValueError):
            validate(c)


if __name__ == '__main__':
    unittest.main()
