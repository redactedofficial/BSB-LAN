"""Read-only transport checks plus non-retained, non-command ACL test messages."""
import json
from pathlib import Path
import ssl
import threading
import paho.mqtt.client as mqtt

credentials = json.loads(Path('/etc/mosquitto/bsblan-admin/credentials.json').read_text())
ha_entries = json.loads(Path('/opt/bms/homeassistant/.storage/core.config_entries').read_text())['data']['entries']
ha_config = next(e['data'] for e in ha_entries if e['domain'] == 'mqtt')
context = ssl.create_default_context(cafile='/etc/mosquitto/bsblan-admin/ca.pem')
connected = threading.Event()
ha_connected = threading.Event()
observed = threading.Event()
results = {}


def connect(c, _u, _flags, reason, _properties):
    if not reason.is_failure:
        connected.set()


def ha_connect(c, _u, _flags, reason, _properties):
    if not reason.is_failure:
        c.subscribe('BSB-LAN/validation', qos=1)


def ha_subscribed(c, _u, _mid, reasons, _properties):
    if not any(reason.is_failure for reason in reasons):
        ha_connected.set()


def published(c, _u, mid, reason, _properties):
    results[mid] = reason.is_failure


ha = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id='bsblan-ha-acl-validation', protocol=mqtt.MQTTv5)
ha.username_pw_set(ha_config['username'], ha_config['password'])
ha.on_connect = ha_connect
ha.on_subscribe = ha_subscribed
ha.on_message = lambda c, u, m: observed.set() if m.topic == 'BSB-LAN/validation' and m.payload == b'transport-check' else None
ha.connect('127.0.0.1', 1883, 15)
ha.loop_start()
assert ha_connected.wait(5), 'HA subscription failed'
device = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id='bsblan-tls-validation', protocol=mqtt.MQTTv5)
device.username_pw_set(credentials['username'], credentials['password'])
device.tls_set_context(context)
device.on_connect = connect
device.on_publish = published
device.connect('10.0.10.29', 8883, 15)
device.loop_start()
try:
    assert connected.wait(5), 'TLS MQTT authentication failed'
    message = device.publish('BSB-LAN/validation', 'transport-check', qos=1, retain=False)
    message.wait_for_publish(timeout=5)
    assert observed.wait(5), 'HA did not receive gateway observation'
    for topic in ('rms/pdu/validation-denied', 'homeassistant/switch/rms_pdu/validation/config'):
        message = device.publish(topic, '{}', qos=1, retain=False)
        message.wait_for_publish(timeout=5)
        assert results.get(message.mid) is True, 'Unrelated namespace was not denied'
    print('Verified TLS MQTT authentication, HA observations, and denied unrelated RMS/discovery topics.')
    print('No parameter commands or hardware operations were sent.')
finally:
    device.disconnect()
    device.loop_stop()
    ha.disconnect()
    ha.loop_stop()
