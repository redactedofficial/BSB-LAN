# MQTT minimal branch

The `mqtt-minimal` branch is a compact BSB-LAN application profile with the
original bus/decoder and MQTT engine. `refined-ui` remains the richer variant.
The minimal firmware has plain status, parameter and essential Settings pages.
No SD card, local history, formatting, charts, raw parameter-dump generation,
external sensor polling or web OTA service is used. Wi-Fi/Ethernet, the native
parameter JSON API, MQTT TLS and Home Assistant discovery remain available.

Retain your private `BSB_LAN_config.h` and Frederik's exact
`BSB_LAN_custom_defs.h`. The personal header is compiled directly; no schema
conversion or parameter renumbering is performed. It is ignored by Git, as are
credentials and configured binaries. Copy the supplied header into BSB_LAN
before building; placing it on an SD card does not install it. Set
`DEFAULT_FLAG FL_SW_CTL_RONLY` in the private config to expose write modes.
The application itself starts read-only until a persisted write level is chosen.
Complete permits writable OEM settings but never overrides explicit read-only
parameter flags.

Build normally for the board with the Minimal SPIFFS partition. Regenerate and
verify the small application assets using:

```text
python ui/build_minimal.py
python ui/verify_engine.py
node ui/test_minimal.cjs
python home-assistant/test_budget.py
```

The budget-template test uses PyYAML and Jinja2 and does not replace running
Home Assistant validation. See [server integration](../home-assistant/README.md)
for MQTT settings, topics and the seasonal budget blueprint.

`gateway_profile.h` selects the profile. The protocol/decoder remains unchanged;
guards in the application omit optional services. The unused temporary
parameter-dump table is reduced to one sentinel entry; Frederik's real table
is intact. Never enable raw table generation in this profile without restoring
the original table capacity. JSON /JI reports the actual software write mode.

Parameter writes use authenticated POST /JS with X-BSB-Token from the page's
gateway-token meta element; the existing parameter/value/type/destination JSON
contract is retained. The local page's HTTP Basic authentication is inherited;
remote web management requires the server's HTTPS proxy or VPN. MQTT commands
remain upstream-compatible. No custom authentication/session framework is added.

Preserve upstream attribution, the CC BY-NC-SA 4.0 license statement in the root
README and bundled dependencies' licenses. This branch is a custom profile,
not an official upstream release. See QA.md for measured validation and limits.
