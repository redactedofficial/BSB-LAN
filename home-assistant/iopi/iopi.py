"""IOPI: read-only header detection and explicitly commissioned MQTT outputs."""
from __future__ import annotations

import argparse
from collections import deque
import json
import logging
from logging.handlers import RotatingFileHandler
import math
import os
from pathlib import Path
import queue
import re
import signal
import socket
import ssl
import subprocess
import threading
import time

VERSION = '0.4.0'
LOG = logging.getLogger('iopi')
# BCM GPIO -> physical 40-pin header position. GPIO0/1 are reserved for HAT ID.
PINS = {2: 3, 3: 5, 4: 7, 5: 29, 6: 31, 7: 26, 8: 24, 9: 21,
        10: 19, 11: 23, 12: 32, 13: 33, 14: 8, 15: 10, 16: 36,
        17: 11, 18: 12, 19: 35, 20: 38, 21: 40, 22: 15, 23: 16,
        24: 18, 25: 22, 26: 37, 27: 13}
RELAY_GPIO = {1: 17, 2: 27, 3: 22, 4: 23, 5: 24, 6: 25, 7: 5, 8: 6}
FEEDBACK = {'BSB-LAN/0/36/8314/status': 'return', 'BSB-LAN/0/31/6700/status': 'error',
            'BSB-LAN/0/37/8830/status': 'buffer'}
LINE = re.compile(r'^\s*(\d+):\s+(\S+)\s+.*?\|\s*(hi|lo|--)\s*//\s*(.*?)\s*=\s*(.*?)\s*$')


def validate(config):
    if not isinstance(config, dict) or config.get('device_id') != 'bmsiopi':
        raise ValueError('Expected device_id bmsiopi')
    if config.get('boiler_control', 'relay') not in ('relay', 'bsb_lan'):
        raise ValueError('Unknown boiler control transport')
    mqtt = config.get('mqtt', {})
    for key in ('host', 'username', 'password_file', 'ca_file'):
        if not isinstance(mqtt.get(key), str) or not mqtt[key]:
            raise ValueError(f'Missing MQTT {key}')
    if type(mqtt.get('port')) is not int or not 1 <= mqtt['port'] <= 65535:
        raise ValueError('Invalid MQTT port')
    rows = config.get('relays')
    if not isinstance(rows, list) or len(rows) != 8:
        raise ValueError('Exactly eight relays required')
    if {r.get('id') for r in rows if isinstance(r, dict)} != set(RELAY_GPIO):
        raise ValueError('Invalid relay IDs')
    for r in rows:
        if (type(r['id']) is not int or type(r.get('gpio')) is not int
                or r['gpio'] != RELAY_GPIO[r['id']]
                or type(r.get('enabled')) is not bool
                or (r.get('active_low') is not None and type(r['active_low']) is not bool)
                or not isinstance(r.get('name'), str) or len(r['name']) > 48):
            raise ValueError('Invalid relay configuration')
        if r['enabled'] and type(r['active_low']) is not bool:
            raise ValueError('Commissioned outputs require confirmed trigger polarity')
    if next(r['enabled'] for r in rows if r['id'] == 1) != next(r['enabled'] for r in rows if r['id'] == 2):
        raise ValueError('Commission boiler and pump together')
    t = config.get('thermostat', {})
    if t.get('gpio') != 26 or type(t.get('enabled')) is not bool or type(t.get('connected')) is not bool:
        raise ValueError('Thermostat must use GPIO26 with an explicit enabled flag')
    for key, low, high in [('lease_seconds', 10, 900), ('max_on_seconds', 10, 3600),
                           ('pump_prime_seconds', 1, 30), ('pump_run_on_seconds', 10, 300),
                           ('return_cutoff', 30, 55)]:
        v = config.get(key)
        if type(v) not in (int, float) or not math.isfinite(v) or not low <= v <= high:
            raise ValueError(f'Invalid {key}')
    if config['lease_seconds'] > config['max_on_seconds']:
        raise ValueError('Lease exceeds continuous run ceiling')
    return config


def notify(message):
    target = os.environ.get('NOTIFY_SOCKET')
    if target:
        if target.startswith('@'):
            target = '\0' + target[1:]
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect(target)
            sock.sendall(message.encode())


def parse_pins(text):
    result = {}
    for line in text.splitlines():
        match = LINE.match(line)
        if not match or int(match[1]) not in PINS:
            continue
        gpio = int(match[1])
        if gpio in result:
            raise ValueError('Duplicate GPIO observation')
        result[gpio] = {'gpio': gpio, 'physical_pin': PINS[gpio],
                        'level': {'hi': 'High', 'lo': 'Low', '--': 'Unknown'}[match[3]],
                        'mode': {'ip': 'Input', 'op': 'Output'}.get(match[2], 'Alternate'),
                        'function': match[5], 'source': 'pinctrl readback'}
    if set(result) != set(PINS):
        raise ValueError('Incomplete header GPIO observation')
    return result


def observe():
    r = subprocess.run(['pinctrl', 'get'], text=True, capture_output=True, timeout=2, check=True)
    return parse_pins(r.stdout)


class GpioHardware:
    def __init__(self, config):
        self.outputs, self.input, self.factory = {}, None, None
        self.input_connected = config['thermostat']['connected']
        # An uncommissioned installation never claims a line or changes its bias.
        if any(r['enabled'] for r in config['relays']) or config['thermostat']['enabled']:
            from gpiozero import OutputDevice, DigitalInputDevice
            from gpiozero.pins.lgpio import LGPIOFactory
            self.factory = LGPIOFactory(chip=0)
            try:
                for r in config['relays']:
                    if r['enabled']:
                        self.outputs[r['id']] = OutputDevice(r['gpio'], active_high=not r['active_low'],
                                                           initial_value=False, pin_factory=self.factory)
                if config['thermostat']['enabled']:
                    self.input = DigitalInputDevice(26, pull_up=True, bounce_time=0.05,
                                                    pin_factory=self.factory)
            except Exception:
                self.close()
                raise

    def set(self, rid, on):
        output = self.outputs[rid]
        output.value = on
        if bool(output.value) != on:
            raise OSError('GPIO readback mismatch')

    def thermostat(self):
        return bool(self.input.value) if self.input is not None and self.input_connected else None

    def close(self):
        for rid in sorted(self.outputs):  # Boiler R1 is released before pump R2.
            try:
                self.outputs[rid].off()
            finally:
                self.outputs[rid].close()
        if self.input is not None:
            self.input.close()
        if self.factory is not None:
            self.factory.close()


class Outputs:
    def __init__(self, config, hardware, clock=time.monotonic):
        self.config, self.hardware, self.clock = config, hardware, clock
        self.enabled = {r['id'] for r in config['relays'] if r['enabled']}
        self.state = {rid: False for rid in self.enabled}
        self.started, self.expires = {}, {}
        self.pump_until = 0.0
        self.fault = False
        self.pump_override = False

    def manual_pump(self, on):
        if 2 not in self.enabled or self.fault:
            return 'gpio_fault' if self.fault else 'not_commissioned'
        self.pump_override = on
        if on:
            self.command(2, True, coordinated=True)
        LOG.info('pump_override=%s', 'ON' if on else 'AUTO')
        return 'accepted'

    def write(self, rid, on):
        if self.state.get(rid) is on:
            return
        # In BSB mode channel 1 is a logical request only. Its physical GPIO
        # remains LOW; a separately supervised BMS service controls the boiler.
        if rid != 1 or self.config.get('boiler_control', 'relay') == 'relay':
            self.hardware.set(rid, on)
        self.state[rid] = on
        LOG.info('channel=%d state=%s transport=%s', rid, 'ON' if on else 'OFF',
                 self.config.get('boiler_control', 'relay') if rid == 1 else 'gpio')
        if on:
            self.started[rid] = self.clock()
        else:
            self.started.pop(rid, None)
            self.expires.pop(rid, None)

    def stop_heat(self):
        if self.state.get(1):
            self.write(1, False)
            if self.state.get(2):
                self.pump_until = max(self.pump_until, self.clock() + self.config['pump_run_on_seconds'])

    def command(self, rid, on, coordinated=False):
        if rid not in self.enabled or self.fault:
            return 'not_commissioned' if not self.fault else 'gpio_fault'
        now = self.clock()
        if rid == 1:
            if on and (not self.state.get(2) or now - self.started.get(2, now) < self.config['pump_prime_seconds']):
                return 'pump_not_primed'
            if not on:
                self.stop_heat()
        if rid == 2 and not on:
            self.stop_heat()
            if self.pump_override:
                self.command(2, True, coordinated=True)
                return 'manual_pump_hold'
            if now < self.pump_until:
                self.expires.pop(2, None)
                return 'pump_run_on'
        self.write(rid, on)
        if on:
            ceiling = (float('inf') if coordinated and rid == 2 else
                       self.started[rid] + self.config['max_on_seconds'])
            self.expires[rid] = min(now + self.config['lease_seconds'], ceiling)
        return 'accepted'

    def tick(self):
        now = self.clock()
        if self.pump_override and not self.fault:
            self.command(2, True, coordinated=True)
        for rid in sorted(list(self.expires)):
            if now >= self.expires.get(rid, float('inf')):
                self.command(rid, False)
                LOG.info('relay=%d event=lease_expired', rid)
        if self.state.get(2) and not self.state.get(1) and now >= self.pump_until and 2 not in self.expires:
            self.write(2, False)

    def disconnect(self):
        self.pump_override = False
        self.stop_heat()
        for rid in sorted(self.enabled):
            self.command(rid, False)

    def emergency(self):
        self.fault = True
        self.pump_override = False
        self.expires.clear()
        for rid in sorted(self.enabled):
            try:
                self.hardware.set(rid, False)
                self.state[rid] = False
            except Exception:
                self.state[rid] = None
        LOG.error('event=gpio_fault outputs=off_requested fault=latched')


class Heater:
    """Comfort control only: native boiler protections remain authoritative."""
    def __init__(self, config, outputs, clock=time.monotonic, wall_clock=time.time):
        self.config, self.outputs, self.clock, self.wall_clock = config, outputs, clock, wall_clock
        self.mode, self.result = 'Off', 'Stopped'
        self.cutoff = config['return_cutoff']
        self.receipts = {}
        self.deadline = 0.0
        self.permission = None
        self.charge_deadline = self.next_charge = 0.0
        self.buffer_warm = False

    def daily_policy(self, payload):
        try:
            policy = json.loads(payload)
            target, expires = policy['target'], policy['expires']
            differential = policy.get('differential', 2)
            minimum, buffer_diff = policy.get('buffer_minimum', 40), policy.get('buffer_differential', 5)
            if (type(policy['allowed']) is not bool or type(target) not in (int, float)
                    or not math.isfinite(target) or not 30 <= target <= 55
                    or type(expires) not in (int, float) or not math.isfinite(expires)
                    or type(differential) not in (int, float) or not math.isfinite(differential) or not 1 <= differential <= 5
                    or not self.wall_clock() < expires <= self.wall_clock() + 90
                    or not isinstance(policy['reason'], str) or len(policy['reason']) > 80):
                raise ValueError('Invalid daily policy')
            if (any(type(policy.get(key, False)) is not bool for key in
                    ('gas_allowed', 'buffer_preferred', 'buffer_window'))
                    or type(minimum) not in (int, float) or not math.isfinite(minimum) or not 35 <= minimum <= 55
                    or type(buffer_diff) not in (int, float) or not math.isfinite(buffer_diff) or not 2 <= buffer_diff <= 10):
                raise ValueError('Invalid buffer policy')
        except (ValueError, TypeError, KeyError):
            return 'invalid_policy'
        self.permission = policy
        self.permission['differential'] = differential
        self.permission.update(buffer_minimum=minimum, buffer_differential=buffer_diff)
        return 'accepted'

    def policy_reason(self):
        if not self.permission or self.wall_clock() >= self.permission['expires']:
            return 'Daily permission expired; waiting for Home Assistant'
        if not self.permission['allowed']:
            return self.permission['reason']
        return None

    def feedback(self, kind, payload):
        try:
            if kind in ('return', 'buffer'):
                value = float(payload)
                if not math.isfinite(value) or not 0 <= value <= 100:
                    raise ValueError('Invalid temperature')
            else:
                value = int(payload.split(' - ', 1)[0])
                if not 0 <= value <= 65535:
                    raise ValueError('Invalid error code')
        except (ValueError, TypeError):
            self.receipts.pop(kind, None)
            return
        self.receipts[kind] = (value, self.clock())

    def fresh(self):
        return all(k in self.receipts and self.clock() - self.receipts[k][1] < 45 for k in ('return', 'error'))

    def buffer_fresh(self):
        return 'buffer' in self.receipts and self.clock() - self.receipts['buffer'][1] < 45

    def block_reason(self):
        if self.outputs.fault:
            return 'GPIO fault'
        if not {1, 2} <= self.outputs.enabled:
            return 'Outputs not commissioned'
        if not self.fresh():
            return 'Waiting for fresh boiler feedback'
        if self.receipts['error'][0] != 0:
            return f'Boiler error {self.receipts["error"][0]}'
        if self.receipts['return'][0] >= self.cutoff:
            return 'Return-water target reached'
        return None

    def stop(self, reason='Stopped'):
        self.mode, self.result = 'Off', reason
        self.outputs.stop_heat()
        if 2 in self.outputs.enabled:
            self.outputs.command(2, False)

    def select(self, mode):
        if mode not in ('Off', 'Thermostat', 'Manual'):
            return 'invalid_mode'
        if mode == 'Off':
            self.stop()
            return 'accepted'
        reason = self.block_reason() if mode == 'Manual' else None
        if mode == 'Thermostat':
            if not (self.config['thermostat']['enabled'] and self.config['thermostat']['connected']):
                reason = 'Delta input not connected'
            elif self.outputs.fault or not {1, 2} <= self.outputs.enabled:
                reason = 'GPIO outputs unavailable'
        if reason:
            self.result = reason
            return 'blocked'
        if mode != self.mode:
            self.deadline = self.clock() + self.config['max_on_seconds']
        self.mode = mode
        return 'accepted'

    def tick(self, demand):
        if self.mode == 'Off':
            return
        if self.mode == 'Thermostat':
            self.tick_daily(demand)
            return
        reason = self.block_reason()
        if self.clock() >= self.deadline:
            reason = 'Maximum heating duration reached'
        if reason:
            self.stop(reason)
            return
        self.outputs.command(2, True)
        status = self.outputs.command(1, True)
        self.result = 'Heating requested' if status == 'accepted' else 'Priming radiator pump'

    def tick_daily(self, demand):
        reason = self.policy_reason()
        if self.outputs.fault:
            reason = 'GPIO fault'
        elif demand is not True:
            reason = 'Waiting for Delta demand' if demand is False else 'Delta input unavailable'
        elif self.fresh() and self.receipts['error'][0] != 0:
            reason = f'Boiler error {self.receipts["error"][0]}'
        if reason:
            self.outputs.stop_heat()
            if 2 in self.outputs.enabled:
                self.outputs.command(2, False)
            self.result = reason
            return
        prefer_buffer = self.permission.get('buffer_preferred', False)
        if not self.buffer_fresh() or not prefer_buffer:
            self.buffer_warm = False
        else:
            temperature = self.receipts['buffer'][0]
            minimum = self.permission['buffer_minimum']
            if temperature >= minimum:
                self.buffer_warm = True
            elif temperature <= minimum - self.permission['buffer_differential']:
                self.buffer_warm = False
        gas_window = self.permission.get('gas_allowed', True)
        if not gas_window and not (self.permission.get('buffer_window', False) and self.buffer_warm):
            self.outputs.stop_heat()
            self.outputs.command(2, False)
            self.result = 'Waiting for usable buffer heat; gas outside schedule'
            return
        # Distribution can use heat already stored in the buffer. It does not
        # depend on a low boiler return temperature or a new burner request.
        self.outputs.command(2, True, coordinated=True)
        target = self.permission['target']
        if self.buffer_warm or not gas_window or (prefer_buffer and not self.buffer_fresh()):
            if self.outputs.state.get(1):
                self.outputs.stop_heat()
                self.next_charge = self.clock() + 600
            self.result = ('Pump on; stored heat first, gas request off' if self.buffer_warm else
                           'Pump on; gas blocked: fresh tank reading needed')
            return
        if not self.fresh():
            self.outputs.stop_heat()
            self.result = 'Pump on; boiler blocked: feedback unavailable'
            return
        now, temperature = self.clock(), self.receipts['return'][0]
        if self.outputs.state.get(1) and now >= self.charge_deadline:
            self.outputs.stop_heat()
            self.next_charge = now + 600
        if temperature >= target:
            if self.outputs.state.get(1):
                self.outputs.stop_heat()
                self.next_charge = now + 600
            self.result = 'Pump on; boiler return target reached'
        elif now < self.next_charge or (not self.outputs.state.get(1) and temperature > target - self.permission['differential']):
            self.result = 'Pump on; boiler resting / within return differential'
        else:
            was_on = self.outputs.state.get(1)
            status = self.outputs.command(1, True)
            if status == 'accepted' and not was_on:
                self.charge_deadline = now + self.config['max_on_seconds']
            self.result = (f'Pump on; boiler requested to {target:g} C return'
                           if status == 'accepted' else 'Priming radiator pump')


def discovery(config):
    prefix = 'iopi/bmsiopi'
    device = {'identifiers': ['bmsiopi'], 'name': 'BMSIOPI', 'manufacturer': 'IOPI',
              'model': 'Raspberry Pi 3 B+ / 8 relay I/O', 'sw_version': VERSION}
    def base(component, key, name, avail='pins_available'):
        return {'name': name, 'unique_id': f'bmsiopi_{key}',
                'default_entity_id': f'{component}.bmsiopi_{key}', 'device': device,
                'availability': [{'topic': f'{prefix}/availability'}, {'topic': f'{prefix}/{avail}'}],
                'availability_mode': 'all', 'state_topic': f'{prefix}/{key}/state',
                'origin': {'name': 'IOPI', 'sw_version': VERSION}}
    names = {r['gpio']: r['name'] for r in config['relays'] if r['name']}
    names[26] = 'Delta demand'
    for gpio in PINS:
        key = f'gpio_{gpio}'
        label = f'GPIO {gpio}' + (f' · {names[gpio]}' if gpio in names else '')
        row = base('sensor', key, label)
        row.update(expire_after=20, json_attributes_topic=f'{prefix}/{key}/attributes',
                   icon='mdi:chip')
        yield f'homeassistant/sensor/bmsiopi/{key}/config', row
    for r in config['relays']:
        key = f'relay_{r["id"]}'
        label = f'Relay {r["id"]}' + (f' · {r["name"]}' if r['name'] else '')
        row = base('switch', key, label, f'{key}/available')
        row.update(command_topic=f'{prefix}/{key}/set', payload_on='ON', payload_off='OFF',
                   optimistic=False, retain=False, qos=0,
                   message_expiry_interval={'seconds': 2},
                   json_attributes_topic=f'{prefix}/{key}/attributes', icon='mdi:electric-switch')
        yield f'homeassistant/switch/bmsiopi/{key}/config', row
    row = base('binary_sensor', 'thermostat', 'Delta heat demand', 'thermostat/available')
    row.update(expire_after=20, icon='mdi:thermostat')
    yield 'homeassistant/binary_sensor/bmsiopi/thermostat/config', row
    row = base('select', 'heating_mode', 'Heating mode', 'system_available')
    row.update(command_topic=f'{prefix}/heating/mode/set', options=['Off', 'Thermostat', 'Manual'],
               retain=False, qos=0, optimistic=False)
    yield 'homeassistant/select/bmsiopi/heating_mode/config', row
    row = base('switch', 'pump_override', 'Manual pump hold', 'system_available')
    row.update(command_topic=f'{prefix}/heating/pump_override/set', payload_on='ON', payload_off='OFF',
               optimistic=False, retain=False, qos=0, icon='mdi:pump')
    yield 'homeassistant/switch/bmsiopi/pump_override/config', row
    row = base('sensor', 'buffer_water', 'Buffer tank water', 'buffer_available')
    row.update(expire_after=20, device_class='temperature', unit_of_measurement='°C', state_class='measurement')
    yield 'homeassistant/sensor/bmsiopi/buffer_water/config', row
    row = base('number', 'return_cutoff', 'Return-water cutoff', 'system_available')
    row.update(command_topic=f'{prefix}/heating/cutoff/set', min=30, max=55, step=1,
               unit_of_measurement='°C', mode='box', retain=False, qos=0)
    yield 'homeassistant/number/bmsiopi/return_cutoff/config', row
    for key, label in [('heating_status', 'Heating control'), ('return_water', 'Return water'), ('boiler_error', 'Boiler error')]:
        row = base('sensor', key, label, 'system_available' if key == 'heating_status' else 'boiler_available')
        row.update(expire_after=20)
        if key == 'return_water':
            row.update(device_class='temperature', unit_of_measurement='°C', state_class='measurement')
        yield f'homeassistant/sensor/bmsiopi/{key}/config', row
    row = base('sensor', 'daily_permission', 'Daily heating permission', 'system_available')
    row.update(expire_after=20, icon='mdi:calendar-check')
    yield 'homeassistant/sensor/bmsiopi/daily_permission/config', row
    row = base('binary_sensor', 'boiler_request', 'Boiler heat request', 'system_available')
    row.update(expire_after=20, icon='mdi:fire')
    yield 'homeassistant/binary_sensor/bmsiopi/boiler_request/config', row
    for key, name in [('status', 'I/O configuration'), ('temperature', 'CPU temperature'),
                       ('power', 'Power status'), ('uptime', 'Uptime')]:
        row = base('sensor', key, name, 'system_available')
        row.update(expire_after=25, entity_category='diagnostic')
        if key == 'temperature':
            row.update(device_class='temperature', unit_of_measurement='°C', state_class='measurement')
        if key == 'uptime':
            row.update(device_class='duration', unit_of_measurement='s', state_class='measurement')
        yield f'homeassistant/sensor/bmsiopi/{key}/config', row


class Node:
    def __init__(self, config, hardware, mqtt_module):
        self.config, self.hardware, self.module = config, hardware, mqtt_module
        self.outputs = Outputs(config, hardware)
        self.heater = Heater(config, self.outputs)
        self.client = mqtt_module.Client(mqtt_module.CallbackAPIVersion.VERSION2,
                                         client_id='bmsiopi', protocol=mqtt_module.MQTTv5)
        password = Path(config['mqtt']['password_file']).read_text(encoding='utf8').strip()
        if not password:
            raise ValueError('Empty MQTT credential')
        self.client.username_pw_set(config['mqtt']['username'], password)
        context = ssl.create_default_context(cafile=config['mqtt']['ca_file'])
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        self.client.tls_set_context(context)
        self.client.will_set('iopi/bmsiopi/availability', 'offline', qos=1, retain=True)
        self.client.on_connect, self.client.on_disconnect = self.on_connect, self.on_disconnect
        self.client.on_message = self.on_message
        self.events = queue.Queue(maxsize=64)
        self.connected = threading.Event()
        self.generation = 0
        self.stop = threading.Event()
        self.born = time.monotonic()
        self.last_observation = None
        self.last_result = {}
        self.rate = deque()

    def pub(self, topic, payload, retain=False):
        if self.connected.is_set():
            return self.client.publish(topic, payload, qos=1, retain=retain)
        return None

    def status(self, key, payload, retain=False):
        return self.pub(f'iopi/bmsiopi/{key}', payload, retain)

    def operator_action(self, action):
        # Command intent is separate from resulting mode. Cutoffs, reconnects
        # and calendar gaps must not be mistaken for someone pressing Stop.
        self.status('heating/operator_action', json.dumps({'action': action, 'at': time.time()}))

    def on_connect(self, client, userdata, flags, reason, properties):
        if reason.is_failure:
            LOG.error('mqtt event=connection_rejected')
            return
        self.generation += 1
        self.connected.set()
        client.subscribe('homeassistant/status', qos=0)
        for topic in FEEDBACK:
            # Suppress stored subscription snapshots, but accept newly published
            # BSB readings even though the gateway itself publishes with RETAIN.
            client.subscribe(topic, options=self.module.SubscribeOptions(qos=0, retainAsPublished=False, retainHandling=2))
        for topic in ['iopi/bmsiopi/heating/mode/set', 'iopi/bmsiopi/heating/cutoff/set',
                      'iopi/bmsiopi/heating/policy/set', 'iopi/bmsiopi/heating/pump_override/set']:
            client.subscribe(topic, options=self.module.SubscribeOptions(qos=0, retainAsPublished=True, retainHandling=2))
        for r in self.config['relays']:
            client.subscribe(f'iopi/bmsiopi/relay_{r["id"]}/set',
                             options=self.module.SubscribeOptions(qos=0, retainAsPublished=True, retainHandling=2))

    def on_disconnect(self, client, userdata, flags, reason, properties):
        self.connected.clear()
        self.generation += 1
        LOG.warning('mqtt event=disconnected')

    def on_message(self, client, userdata, msg):
        if msg.topic == 'homeassistant/status':
            if msg.payload == b'online':
                try:
                    self.events.put_nowait(('discovery', self.generation, time.monotonic()))
                except queue.Full:
                    pass
            return
        if msg.retain or msg.dup or len(msg.payload) > (512 if msg.topic == 'iopi/bmsiopi/heating/policy/set' else 128):
            LOG.warning('mqtt event=invalid_or_replayed_command')
            return
        if msg.topic in FEEDBACK or msg.topic in ('iopi/bmsiopi/heating/mode/set', 'iopi/bmsiopi/heating/cutoff/set',
                                                'iopi/bmsiopi/heating/policy/set', 'iopi/bmsiopi/heating/pump_override/set'):
            try:
                payload = msg.payload.decode('utf8')
                kind = 'feedback' if msg.topic in FEEDBACK else 'setting'
                self.events.put_nowait((kind, self.generation, time.monotonic(), msg.topic, payload))
            except (UnicodeError, queue.Full):
                pass
            return
        if msg.payload not in (b'ON', b'OFF'):
            return
        match = re.fullmatch(r'iopi/bmsiopi/relay_([1-8])/set', msg.topic)
        if not match:
            return
        try:
            self.events.put_nowait(('command', self.generation, time.monotonic(), int(match[1]), msg.payload == b'ON'))
        except queue.Full:
            LOG.warning('mqtt event=command_queue_full')

    def advertise(self):
        for topic, row in discovery(self.config):
            self.pub(topic, json.dumps(row), True)

    def publish_snapshot(self):
        rows = self.last_observation
        self.status('pins_available', 'online' if rows is not None else 'offline', True)
        for gpio in PINS:
            if rows is not None:
                self.status(f'gpio_{gpio}/state', rows[gpio]['level'])
                self.status(f'gpio_{gpio}/attributes', json.dumps(rows[gpio]))
        for r in self.config['relays']:
            rid, key = r['id'], f'relay_{r["id"]}'
            native = rid == 1 and self.config.get('boiler_control') == 'bsb_lan'
            available = rid in self.outputs.enabled and not self.outputs.fault and rows is not None
            if available:
                drive = False if native else self.outputs.state[rid]
                expected = 'Low' if drive == r['active_low'] else 'High'
                available = rows[r['gpio']]['mode'] == 'Output' and rows[r['gpio']]['level'] == expected
            self.status(f'{key}/available', 'online' if available and not native else 'offline', True)
            if available:
                self.status(f'{key}/state', 'ON' if drive else 'OFF')
            self.status(f'{key}/attributes', json.dumps({
                'gpio': r['gpio'], 'physical_pin': PINS[r['gpio']],
                'commissioned': r['enabled'], 'active_low': r['active_low'],
                'last_result': self.last_result.get(rid, 'not_commissioned' if not r['enabled'] else 'idle'),
                'state_source': 'GPIO drive readback; no contact/load feedback',
                'reserved_off': native,
                'manual_hold': self.outputs.pump_override if rid == 2 else False,
                'lease_seconds': self.config['lease_seconds']}))
        heat = self.hardware.thermostat()
        self.status('thermostat/available', 'online' if heat is not None else 'offline', True)
        if heat is not None:
            self.status('thermostat/state', 'ON' if heat else 'OFF')
        commissioned = len(self.outputs.enabled)
        self.status('status/state', 'GPIO fault' if self.outputs.fault else
                    f'{commissioned}/8 outputs enabled; Delta ' +
                    ('connected' if heat is not None else 'not connected'))
        try:
            temp = int(Path('/sys/class/thermal/thermal_zone0/temp').read_text()) / 1000
            self.status('temperature/state', str(temp))
            power = subprocess.run(['vcgencmd', 'get_throttled'], text=True, capture_output=True, timeout=2, check=True)
            bits = int(power.stdout.strip().split('=')[1], 16)
            label = ('Undervoltage now' if bits & 1 else 'Throttled now' if bits & 4 else
                     'Earlier undervoltage' if bits & 0x10000 else 'Normal')
            self.status('power/state', label)
        except (OSError, ValueError, IndexError, subprocess.SubprocessError):
            # Publish no invented zero/normal reading: existing sensor states expire.
            pass
        self.status('uptime/state', str(int(time.monotonic() - self.born)))
        self.status('heating_mode/state', self.heater.mode)
        self.status('pump_override/state', 'ON' if self.outputs.pump_override else 'OFF')
        buffer_fresh = self.heater.buffer_fresh()
        self.status('buffer_available', 'online' if buffer_fresh else 'offline', True)
        if buffer_fresh:
            self.status('buffer_water/state', str(self.heater.receipts['buffer'][0]))
        self.status('boiler_request/state', 'ON' if self.outputs.state.get(1) else 'OFF')
        if self.config.get('boiler_control') == 'bsb_lan':
            target = (self.heater.permission['target'] if self.heater.mode == 'Thermostat'
                      and self.heater.permission else self.heater.cutoff)
            self.status('heating/boiler_request', json.dumps({
                'active': bool(self.outputs.state.get(1)), 'expires': time.time() + 15,
                'cutoff': target, 'flow': min(target + 5, 60), 'mode': self.heater.mode}))
        self.status('return_cutoff/state', str(self.heater.cutoff))
        self.status('heating_status/state', self.heater.result)
        reason = self.heater.policy_reason()
        self.status('daily_permission/state', ('Blocked: ' + reason if reason else
                    'Allowed: ' + self.heater.permission['reason']))
        fresh = self.heater.fresh()
        self.status('boiler_available', 'online' if fresh else 'offline', True)
        if fresh:
            self.status('return_water/state', str(self.heater.receipts['return'][0]))
            self.status('boiler_error/state', str(self.heater.receipts['error'][0]))
        self.status('system_available', 'online', True)

    def run(self):
        self.client.connect_async(self.config['mqtt']['host'], self.config['mqtt']['port'],
                                  keepalive=15, clean_start=True)
        self.client.loop_start()
        generation, next_poll, next_publish, next_feedback, next_watchdog = -1, 0.0, 0.0, 0.0, 0.0
        notify('READY=1')
        try:
            while not self.stop.wait(0.1):
                now = time.monotonic()
                if generation != self.generation:
                    self.heater.stop('Connection changed; stopped')
                    self.outputs.disconnect()
                    self.heater.receipts.clear()
                    self.heater.permission = None
                    generation = self.generation
                    self.last_observation = None
                    if self.connected.is_set():
                        self.status('availability', 'offline', True)
                        self.advertise()
                        next_poll = next_publish = 0
                if now >= next_poll:
                    try:
                        self.last_observation = observe()
                    except (OSError, ValueError, subprocess.SubprocessError):
                        self.last_observation = None
                        self.heater.stop('GPIO readback unavailable')
                        self.outputs.disconnect()
                    next_poll = now + 2
                try:
                    self.heater.tick(self.hardware.thermostat())
                    self.outputs.tick()
                except (OSError, RuntimeError):
                    self.outputs.emergency()
                    self.heater.mode, self.heater.result = 'Off', 'GPIO fault'
                for _ in range(16):
                    try:
                        event = self.events.get_nowait()
                    except queue.Empty:
                        break
                    if event[1] != generation or not self.connected.is_set() or now - event[2] > 2:
                        continue
                    if event[0] == 'discovery':
                        self.advertise()
                        next_publish = 0
                    elif event[0] == 'feedback':
                        self.heater.feedback(FEEDBACK[event[3]], event[4])
                    elif event[0] == 'setting':
                        if event[3].endswith('/mode/set'):
                            self.heater.select(event[4])
                            if event[4] == 'Off':
                                self.operator_action('stop')
                        elif event[3].endswith('/policy/set'):
                            self.heater.daily_policy(event[4])
                        elif event[3].endswith('/pump_override/set'):
                            if event[4] in ('ON', 'OFF') and self.last_observation is not None:
                                self.outputs.manual_pump(event[4] == 'ON')
                        else:
                            try:
                                value = float(event[4])
                                if math.isfinite(value) and 30 <= value <= 55 and value.is_integer():
                                    self.heater.cutoff = value
                            except ValueError:
                                pass
                        next_publish = 0
                    else:
                        while self.rate and now - self.rate[0] > 1:
                            self.rate.popleft()
                        if len(self.rate) >= 8:
                            continue
                        self.rate.append(now)
                        rid, on = event[3:]
                        if self.last_observation is None:
                            result = 'readback_unavailable'
                        else:
                            if rid == 1:
                                result = ('reserved_off_use_heating_controls' if self.config.get('boiler_control') == 'bsb_lan'
                                          else self.heater.select('Manual' if on else 'Off'))
                            else:
                                result = (self.outputs.manual_pump(on) if rid == 2 else
                                          self.outputs.command(rid, on))
                            # Read hardware again before acknowledging a changed drive state.
                            self.last_observation = observe()
                        self.last_result[rid] = result
                        LOG.info('relay=%d request=%s result=%s', rid, on, result)
                        next_publish = 0
                if now >= next_publish and self.connected.is_set():
                    self.publish_snapshot()
                    self.status('availability', 'online', True)
                    next_publish = now + 5
                if now >= next_feedback and self.connected.is_set():
                    for topic in FEEDBACK:
                        self.pub(topic.removesuffix('/status') + '/poll', '')
                    next_feedback = now + 15
                if now >= next_watchdog:
                    notify('WATCHDOG=1')
                    next_watchdog = now + 5
        finally:
            try:
                self.outputs.disconnect()
                until = time.monotonic() + self.config['pump_run_on_seconds'] + 1
                while self.outputs.state.get(2) and time.monotonic() < until:
                    self.outputs.tick()
                    time.sleep(0.1)
                receipt = self.status('availability', 'offline', True)
                if receipt is not None:
                    receipt.wait_for_publish(timeout=2)
                self.client.disconnect()
            finally:
                self.client.loop_stop()
                self.hardware.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='/etc/iopi/config.json')
    parser.add_argument('--check', action='store_true', help='validate configuration without hardware/network access')
    args = parser.parse_args()
    config = validate(json.loads(Path(args.config).read_text(encoding='utf8')))
    if args.check:
        print(f'Valid: {len(PINS)} usable GPIOs; 8 relays; '
              f'{sum(r["enabled"] for r in config["relays"])} outputs commissioned')
        return
    model = Path('/proc/device-tree/model').read_text().rstrip('\x00')
    if 'Raspberry Pi 3 Model B Plus' not in model:
        raise ValueError('This profile requires a Raspberry Pi 3 Model B Plus')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    log_dir = os.environ.get('LOGS_DIRECTORY')
    if log_dir:
        LOG.addHandler(RotatingFileHandler(Path(log_dir) / 'audit.log', maxBytes=1_000_000, backupCount=3))
    import paho.mqtt.client as mqtt
    hardware = GpioHardware(config)
    try:
        node = Node(config, hardware, mqtt)
    except Exception:
        hardware.close()
        raise
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: node.stop.set())
    node.run()


if __name__ == '__main__':
    main()
