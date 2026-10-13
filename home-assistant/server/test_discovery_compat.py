import json
import unittest
from discovery_compat import normalize, NUMERIC_TEMPLATE


class DiscoveryTests(unittest.TestCase):
    topic = 'homeassistant/sensor/BSB-LAN/8326/config'

    def test_missing_numeric_and_idempotence(self):
        original = {'state_topic': 'BSB-LAN/0/37/8326/status', 'unit_of_measurement': '%'}
        result = normalize(self.topic, json.dumps(original))
        self.assertEqual(json.loads(result)['value_template'], NUMERIC_TEMPLATE)
        self.assertIsNone(normalize(self.topic, result))

    def test_microamp_preserves_value_unit(self):
        original = {'state_topic': 'BSB-LAN/0/38/9618/status', 'unit_of_measurement': 'µA', 'device_class': 'current'}
        result = json.loads(normalize(self.topic, json.dumps(original)))
        self.assertEqual(result['unit_of_measurement'], 'µA')
        self.assertNotIn('device_class', result)

    def test_control_and_unrelated_topics_ignored(self):
        data = json.dumps({'state_topic': 'BSB-LAN/0/1/710/status'})
        self.assertIsNone(normalize('homeassistant/text/BSB-LAN/710/config', data))
        self.assertIsNone(normalize('homeassistant/sensor/rms_pdu/temperature/config', data))

    def test_cumulative_gas_energy_and_idempotence(self):
        for parameter in ('8378', '8379', '8380'):
            with self.subTest(parameter=parameter):
                topic = f'homeassistant/sensor/BSB-LAN/{parameter}-123-231-182820052/config'
                original = {'state_topic': f'BSB-LAN/0/36/{parameter}/status',
                            'unit_of_measurement': 'kWh', 'device_class': 'energy'}
                result = normalize(topic, json.dumps(original))
                self.assertEqual(json.loads(result)['state_class'], 'total_increasing')
                self.assertEqual(json.loads(result)['value_template'], NUMERIC_TEMPLATE)
                self.assertIsNone(normalize(topic, result))

    def test_stock_relative_state_topic(self):
        original = {'~': 'BSB-LAN/0/36/8380', 'state_topic': '~/status',
                    'unit_of_measurement': 'kWh', 'device_class': 'energy'}
        result = normalize(self.topic, json.dumps(original))
        fixed = json.loads(result)
        self.assertEqual(fixed['state_class'], 'total_increasing')
        self.assertEqual(fixed['state_topic'], '~/status')
        self.assertEqual(fixed['~'], original['~'])
        self.assertEqual(fixed['name'], 'Estimated gas energy (heating + hot water)')
        self.assertEqual(fixed['icon'], 'mdi:fire')
        self.assertIsNone(normalize(self.topic, result))

    def test_unrelated_relative_state_topic_ignored(self):
        original = {'~': 'rms/0/36/8380', 'state_topic': '~/status',
                    'unit_of_measurement': 'kWh', 'device_class': 'energy'}
        self.assertIsNone(normalize(self.topic, json.dumps(original)))

    def test_other_energy_readings_not_marked_cumulative(self):
        for state_topic, unit, device_class in (
                ('BSB-LAN/0/36/8383/status', 'kWh', 'energy'),
                ('BSB-LAN/0/36/8380/status', 'W', 'power'),
                ('BSB-LAN/10/36/8380/status', 'kWh', 'energy'),
                ('BSB-LAN/0/37/8380/status', 'kWh', 'energy')):
            with self.subTest(state_topic=state_topic, unit=unit):
                original = {'state_topic': state_topic, 'unit_of_measurement': unit,
                            'device_class': device_class}
                fixed = json.loads(normalize(self.topic, json.dumps(original)))
                self.assertNotIn('state_class', fixed)


if __name__ == '__main__':
    unittest.main()
