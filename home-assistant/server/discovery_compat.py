"""Adapt stock BSB-LAN sensor discovery for HA; never subscribe to control topics."""
import json
import os
from pathlib import Path
import logging
import paho.mqtt.client as mqtt

NUMERIC_TEMPLATE = "{{ value if is_number(value) else 'None' }}"
TOPIC = 'homeassistant/sensor/BSB-LAN/+/config'
CUMULATIVE_GAS_ENERGY = {'8378', '8379', '8380'}


def normalize(topic, payload):
    parts = topic.split('/')
    if len(parts) != 5 or parts[:3] != ['homeassistant', 'sensor', 'BSB-LAN'] or parts[-1] != 'config':
        return None
    if not payload or len(payload) > 65536:
        return None
    config = json.loads(payload)
    if not isinstance(config, dict):
        return None
    state_topic = config.get('state_topic', '')
    if not isinstance(state_topic, str):
        return None
    if state_topic.startswith('~/') and isinstance(config.get('~'), str):
        state_topic = config['~'] + state_topic[1:]
    if not state_topic.startswith('BSB-LAN/'):
        return None
    fixed = dict(config)
    state_parts = state_topic.split('/')
    # These LMS producer parameters are cumulative gas energy, not instantaneous
    # consumption. Restrict the metadata fix to the verified kWh counters.
    if (len(state_parts) == 5 and state_parts[:3] == ['BSB-LAN', '0', '36']
            and state_parts[3] in CUMULATIVE_GAS_ENERGY
            and state_parts[4] == 'status'
            and fixed.get('unit_of_measurement') == 'kWh'
            and fixed.get('device_class') == 'energy'):
        fixed['state_class'] = 'total_increasing'
        if state_parts[3] == '8380':
            fixed['name'] = 'Estimated gas energy (heating + hot water)'
            fixed['icon'] = 'mdi:fire'
    if fixed.get('device_class') == 'current' and fixed.get('unit_of_measurement') in ('µA', 'μA', 'uA'):
        fixed.pop('device_class')  # Preserve the original microamp values and unit.
    if fixed.get('unit_of_measurement') or fixed.get('state_class'):
        fixed['value_template'] = NUMERIC_TEMPLATE
    if fixed == config:
        return None
    return json.dumps(fixed, ensure_ascii=False, separators=(',', ':'))


def main():
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    credential_file = Path(os.environ['CREDENTIALS_DIRECTORY']) / 'mqtt.json'
    credentials = json.loads(credential_file.read_text())
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                         client_id='bsblan-discovery-compat', protocol=mqtt.MQTTv5)
    client.username_pw_set(credentials['username'], credentials['password'])
    client.reconnect_delay_set(min_delay=5, max_delay=60)

    def connect(c, _u, _f, reason, _p):
        if not reason.is_failure:
            c.subscribe(TOPIC, qos=1)
            logging.info('BSB-LAN discovery compatibility connected')
        else:
            logging.error('MQTT authentication failed')

    def message(c, _u, msg):
        try:
            payload = normalize(msg.topic, msg.payload)
            if payload is not None:
                c.publish(msg.topic, payload, qos=1, retain=True)
        except (ValueError, TypeError, AttributeError):
            logging.warning('Invalid sensor discovery ignored')

    client.on_connect = connect
    client.on_message = message
    client.connect('127.0.0.1', 1883, 30)
    client.loop_forever()


if __name__ == '__main__':
    main()
