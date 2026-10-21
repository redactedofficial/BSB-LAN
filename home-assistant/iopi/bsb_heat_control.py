"""BSB-LAN circuit-1 heat requests; IO-PI R1 stays physically off.

This controls comfort settings, never ignition, gas valves or OEM safety limits.
Native settings have no expiring lease: a complete loss of BMS/gateway
communication can prevent the software cutoff. Native temperature limits remain.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
from pathlib import Path
import signal
import socket
import threading
import time

LOG = logging.getLogger('bsbheat')
PARAMETERS = {700: 9, 742: 9, 741: 9, 5977: 29, 5978: 29, 7865: 33,
              8749: 37, 6700: 31, 8314: 36, 8000: 34, 8005: 34, 8326: 36}
TOPICS = {p: f'BSB-LAN/0/{c}/{p}' for p, c in PARAMETERS.items()}
PREFIX = 'iopi/bmsiopi/'
REQUEST = PREFIX + 'heating/boiler_request'


class RequestEnded(RuntimeError):
    """Normal demand cancellation or measured return cutoff, not a fault."""


def decode_request(payload, now):
    row = json.loads(payload)
    if (not isinstance(row, dict) or type(row.get('active')) is not bool
            or row.get('mode') not in ('Off', 'Manual', 'Thermostat')):
        raise ValueError('Invalid heat request')
    for key, low, high in [('expires', now, now + 20), ('cutoff', 30, 55), ('flow', 35, 60)]:
        v = row.get(key)
        if type(v) not in (int, float) or not math.isfinite(v) or not low <= v <= high:
            raise ValueError('Invalid request ' + key)
    if row['expires'] <= now or row['flow'] != min(row['cutoff'] + 5, 60):
        raise ValueError('Expired or inconsistent heat request')
    if row['active'] and row['mode'] == 'Off':
        raise ValueError('Off cannot request heat')
    return row


class Controller:
    """Own and restore only the three settings used by an acknowledged cycle."""
    def __init__(self, io, journal, clock=time.monotonic):
        self.io, self.journal, self.clock = io, Path(journal), clock
        self.owned = json.loads(self.journal.read_text()) if self.journal.exists() else None
        self.started = clock()
        self.status = 'Waiting for fresh request'

    def save(self):
        tmp = self.journal.with_suffix('.next')
        tmp.write_text(json.dumps(self.owned) + '\n')
        os.chmod(tmp, 0o600)
        tmp.replace(self.journal)

    def release(self, reason):
        if not self.owned:
            self.status = reason
            return
        # Keep the journal until every required restoration is confirmed.
        # A crash during any write is recovered on the next service start.
        self.io.set_checked(700, 0)
        h5, flow = self.io.number(5978), self.io.number(742)
        if h5 == 0:
            self.io.set_checked(5978, self.owned['h5'])
        elif h5 != self.owned['h5']:
            raise RuntimeError('H5 changed outside this controller')
        if abs(flow - self.owned['flow']) < 0.11:
            self.io.set_checked(742, self.owned['saved_flow'])
        # A changed flow belongs to the operator and is preserved.
        self.owned = None
        self.journal.unlink(missing_ok=True)
        self.status = reason
        LOG.info('cycle=stopped reason=%s', reason)

    def start(self, request):
        if (self.io.number(5977) != 18 or self.io.number(5978) != 1
                or self.io.number(7865) != 0):
            raise RuntimeError('Expected HC1 H5 normally-open contact, physically open')
        if self.io.number(700) not in (0, 1, 2, 3):
            raise RuntimeError('Unexpected circuit-1 operating mode')
        if self.io.number(741) < request['flow']:
            raise RuntimeError('Requested flow exceeds native HC1 maximum')
        self.owned = {'h5': 1, 'saved_flow': self.io.number(742), 'flow': request['flow']}
        self.save()
        for parameter, value in [(700, 0), (742, request['flow']), (5978, 0)]:
            self.io.guard(request)
            self.io.set_checked(parameter, value)
        self.io.guard(request)
        self.io.set_checked(700, 3)
        self.started = self.clock()
        self.status = 'BSB-LAN heat requested; waiting for native burner status'
        LOG.info('cycle=started flow=%g cutoff=%g transport=bsb_lan', request['flow'], request['cutoff'])

    def step(self):
        request = self.io.request()
        if not request or not request['active']:
            self.release('Stopped; no current heat request')
            return
        try:
            self.io.guard(request)
            if self.owned and self.clock() - self.started >= 3600:
                raise RuntimeError('Maximum heating duration reached')
            if self.owned and request['flow'] != self.owned['flow']:
                self.release('Flow target changed; restarting through checks')
            if not self.owned:
                self.start(request)
            elif (self.io.number(5977) != 18 or self.io.number(5978) != 0
                    or self.io.number(7865) != 0 or self.io.number(700) != 3
                    or abs(self.io.number(742) - self.owned['flow']) > 0.11):
                raise RuntimeError('Native circuit-1 settings changed; stopping owned cycle')
            else:
                self.status = 'BSB-LAN heat requested · ' + self.io.text(8005)
        except RequestEnded as exc:
            self.release(str(exc))
        except Exception:
            self.io.cancel()
            raise


class MqttIO:
    def __init__(self, config, module):
        self.module, self.values = module, {}
        self.connected = threading.Event()
        self.client = module.Client(module.CallbackAPIVersion.VERSION2,
                                    client_id='bsb-heat-control', protocol=module.MQTTv5)
        self.client.username_pw_set(config['username'], config['password'])
        self.client.will_set(PREFIX + 'bsb/availability', 'offline', qos=1, retain=True)
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = lambda *args: self.connected.clear()
        self.client.on_message = self.on_message
        self.client.connect(config['host'], config.get('port', 1883), 15)
        self.client.loop_start()

    def publish(self, topic, payload, retain=False):
        if not self.connected.is_set():
            raise RuntimeError('MQTT unavailable; native stop cannot yet be confirmed')
        return self.client.publish(topic, payload, qos=0, retain=retain)

    def on_connect(self, client, userdata, flags, reason, properties):
        if reason.is_failure:
            return
        self.values.clear()
        for topic in [REQUEST, PREFIX + 'availability', PREFIX + 'relay_1/state',
                      PREFIX + 'relay_2/state', PREFIX + 'relay_2/available'] + [b + '/status' for b in TOPICS.values()]:
            client.subscribe(topic, options=self.module.SubscribeOptions(
                retainAsPublished=False, retainHandling=2))
        self.connected.set()

    def on_message(self, client, userdata, message):
        if not message.retain and len(message.payload) <= 512:
            try:
                self.values[message.topic] = (message.payload.decode('utf8'), time.monotonic())
            except UnicodeError:
                pass

    def text(self, parameter):
        return self.read(TOPICS[parameter] + '/status', 35)

    def number(self, parameter):
        result = float(self.text(parameter).split(' - ', 1)[0])
        if not math.isfinite(result):
            raise RuntimeError('Invalid native reading')
        return result

    def read(self, topic, max_age=20):
        value, received = self.values.get(topic, ('', 0))
        if not self.connected.is_set() or time.monotonic() - received >= max_age:
            raise RuntimeError('Fresh readback missing: ' + topic)
        return value

    def request(self):
        try:
            return decode_request(self.read(REQUEST, 18), time.time())
        except (RuntimeError, ValueError, TypeError):
            return None

    def guard(self, expected):
        current = self.request()
        if not current or not current['active'] or any(current[k] != expected[k] for k in ('flow', 'cutoff', 'mode')):
            raise RequestEnded('Heat request ended or changed')
        for key, value in [('availability', 'online'), ('relay_1/state', 'OFF'),
                           ('relay_2/state', 'ON'), ('relay_2/available', 'online')]:
            if self.read(PREFIX + key, 15) != value:
                raise RuntimeError('Pump / reserved R1 interlock: ' + key)
        if self.number(6700) != 0:
            raise RuntimeError('Native boiler fault; request stopped')
        if self.number(8314) >= expected['cutoff']:
            raise RequestEnded('Return-water target reached')

    def poll(self):
        for base in TOPICS.values():
            self.publish(base + '/poll', '')

    def set_checked(self, parameter, value):
        if parameter not in (700, 742, 5978):
            raise ValueError('Parameter outside comfort-control allowlist')
        sent = time.monotonic()
        self.publish(TOPICS[parameter] + '/set', str(value))
        # Confirm a fresh post-command reply, never an optimistic HA state.
        while time.monotonic() - sent < 8:
            self.publish(TOPICS[parameter] + '/poll', '')
            time.sleep(0.5)
            payload, received = self.values.get(TOPICS[parameter] + '/status', ('', 0))
            try:
                if received >= sent and abs(float(payload.split(' - ', 1)[0]) - value) < 0.11:
                    LOG.info('parameter=%d confirmed=%s', parameter, payload)
                    return
            except ValueError:
                pass
        raise RuntimeError(f'Native write {parameter} unconfirmed')

    def cancel(self, fault=True):
        if fault:
            self.publish(PREFIX + 'heating/native_fault', json.dumps({'at': time.time()}))
        self.publish(PREFIX + 'heating/mode/set', 'Off')

    def advertise(self):
        device = {'identifiers': ['bmsiopi'], 'name': 'BMSIOPI'}
        for key, name in [('control', 'BSB-LAN heating control'), ('native_status', 'Native boiler status')]:
            row = {'name': name, 'unique_id': 'bmsiopi_bsb_' + key,
                   'default_entity_id': 'sensor.bmsiopi_bsb_' + key, 'device': device,
                   'state_topic': PREFIX + 'bsb/' + key, 'expire_after': 30,
                   'availability_topic': PREFIX + 'bsb/availability', 'icon': 'mdi:fire'}
            self.publish(f'homeassistant/sensor/bmsiopi/bsb_{key}/config', json.dumps(row), True)


def notify(message):
    address = os.environ.get('NOTIFY_SOCKET')
    if address:
        if address.startswith('@'):
            address = '\0' + address[1:]
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect(address)
            sock.sendall(message.encode())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='/etc/bsbheat/mqtt.json')
    parser.add_argument('--journal', default='/var/lib/bsbheat/owned-cycle.json')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    import paho.mqtt.client as mqtt
    io = MqttIO(json.loads(Path(args.config).read_text()), mqtt)
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *unused: stop.set())
    controller = Controller(io, args.journal)
    recovering = controller.owned is not None
    next_poll, next_advertise, next_status = 0.0, 0.0, 0.0
    notify('READY=1')
    try:
        while not stop.wait(0.5):
            notify('WATCHDOG=1')
            try:
                if not io.connected.is_set():
                    continue
                if time.monotonic() >= next_poll:
                    io.poll()
                    next_poll = time.monotonic() + 10
                if time.monotonic() >= next_advertise:
                    io.advertise()
                    next_advertise = time.monotonic() + 60
                if recovering:
                    io.cancel(fault=False)
                    controller.release('Recovered interrupted cycle; stopped')
                    recovering = False
                controller.step()
            except Exception as exc:
                LOG.warning('control=%s', exc)
                controller.status = str(exc)
                try:
                    controller.release('Stopped: ' + str(exc))
                except Exception as recovery_error:
                    LOG.error('stop=unconfirmed error=%s', recovery_error)
                    controller.status = 'STOP UNCONFIRMED; retrying native restoration'
            if io.connected.is_set() and time.monotonic() >= next_status:
                next_status = time.monotonic() + 5
                io.publish(PREFIX + 'bsb/availability', 'online', True)
                io.publish(PREFIX + 'bsb/control', controller.status[:240])
                try:
                    io.publish(PREFIX + 'bsb/native_status', io.text(8005))
                except RuntimeError:
                    pass
    finally:
        try:
            io.cancel(fault=False)
            controller.release('Service stopped')
            io.publish(PREFIX + 'bsb/availability', 'offline', True)
        finally:
            io.client.disconnect()
            io.client.loop_stop()


if __name__ == '__main__':
    main()
