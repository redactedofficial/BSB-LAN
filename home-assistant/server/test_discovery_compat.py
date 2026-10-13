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


if __name__ == '__main__':
    unittest.main()
