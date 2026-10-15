"""Generate an uncommissioned example or an explicitly confirmed deployment profile."""
import argparse
import json
from pathlib import Path
from iopi import RELAY_GPIO, validate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--broker', default='mqtt.example.invalid')
    parser.add_argument('--confirmed-high-trigger', action='store_true',
                        help='enable all eight outputs, only after verifying HIGH energises them')
    parser.add_argument('--output', type=Path, default=Path(__file__).with_name('config.example.json'))
    args = parser.parse_args()
    if args.confirmed_high_trigger and args.broker == 'mqtt.example.invalid':
        parser.error('An enabled profile requires an explicit broker hostname')
    if args.confirmed_high_trigger and args.output.name != 'config.json':
        parser.error('Write enabled deployment profiles to ignored config.json')
    config = {
        'device_id': 'bmsiopi',
        'mqtt': {'host': args.broker, 'port': 8883, 'username': 'iopi_node',
                 'password_file': '/etc/iopi/mqtt.password', 'ca_file': '/etc/iopi/mqtt-ca.pem'},
        'relays': [{'id': rid, 'gpio': gpio, 'name': {1: 'Boiler request', 2: 'Radiator pump'}.get(rid, ''),
                    'enabled': args.confirmed_high_trigger,
                    'active_low': False if args.confirmed_high_trigger else None}
                   for rid, gpio in RELAY_GPIO.items()],
        'thermostat': {'gpio': 26, 'enabled': args.confirmed_high_trigger, 'connected': False},
        'lease_seconds': 300, 'max_on_seconds': 3600,
        'pump_prime_seconds': 5, 'pump_run_on_seconds': 120, 'return_cutoff': 45,
    }
    validate(config)
    # Never overwrite an existing profile or change a live configuration implicitly.
    with args.output.open('x', encoding='utf8') as output:
        output.write(json.dumps(config, indent=2) + '\n')
    print(f'Created {args.output.name}; Delta remains disconnected.')


if __name__ == '__main__':
    main()
