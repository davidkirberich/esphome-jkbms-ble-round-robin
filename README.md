# ESPHome JK-BMS BLE Round Robin

An ESPHome YAML package that connects an ESP32 to multiple JK-BMS devices
**one at a time**, for installations where simultaneous BLE connections are
unreliable. Measurements reach Home Assistant through the native ESPHome API,
not MQTT.

The package builds on
[syssi/esphome-jk-bms](https://github.com/syssi/esphome-jk-bms): syssi provides
the BMS protocol and entities; this repository provides the scheduler.

**Why a fixed syssi commit instead of `main`?** The examples pin the upstream
component to `b4f711d180671143c35f9e36079f8652591c52a8`, a previously compiled
version, so a new build does not silently change both the scheduler and the
BMS component. This makes troubleshooting reproducible, not bug-free.
The remote scheduler currently follows `main` for testing; pin its `ref` to a
commit or release tag for a stable deployment.

## Requirements

- ESPHome **2026.9.0 or newer**, using ESP-IDF and a BLE-capable ESP32.
  See [syssi's hardware requirements](https://github.com/syssi/esphome-jk-bms#requirements).
  Its UART examples also support ESP8266; **this BLE package does not**.
- A Bluetooth-compatible JK-BMS and the correct protocol version: check
  [syssi's supported-device list](https://github.com/syssi/esphome-jk-bms#supported-devices),
  including each entry's BLE/UART and firmware notes. The examples use `JK02_32S`.
- Wi-Fi credentials and the Bluetooth MAC address of each BMS.

## Quick start

1. Download the repository. Copy [two-bms.yaml](./examples/two-bms.yaml) and
   [round_robin.yaml](./packages/round_robin.yaml) into your ESPHome configuration
   directory, keeping the `examples/` and `packages/` folders.
2. Add these entries to your ESPHome `secrets.yaml`:

   ```yaml
   wifi_ssid: "your-wifi"
   wifi_password: "your-password"
   bms1_mac_address: "AA:BB:CC:DD:EE:01"
   bms2_mac_address: "AA:BB:CC:DD:EE:02"
   ```

3. Check `name`, `esp32.board`, and `protocol_version` in the example.
   Install it using ESPHome Device Builder; the first flash may require USB.
4. Add the device through Home Assistant's **ESPHome integration**.
   Check both BMS voltage, online status, and data-age entities.

## Which example?

| Example | Intended use | What to adapt |
| --- | --- | --- |
| [two-bms.yaml](./examples/two-bms.yaml) | Recommended starting point: two BMS with essential measurements, errors and data age | Board, protocol, Wi-Fi and two MAC secrets; requires the local package |
| [five-bms.yaml](./examples/five-bms.yaml) | Five BMS, or a template for three/four | Same settings plus all MAC secrets; remove unused BMS entries for fewer devices |
| [jk-bms-gateway.yaml](./examples/jk-bms-gateway.yaml) | Full two-BMS configuration with measurements, controls and gateway diagnostics | Installation-specific `bms200`/`bms300` MAC secrets and primary/backup Wi-Fi secrets; imports the package from GitHub |

The gateway example preserves the original installation's entity names. It uses
90-second turns and **experimental full BLE restart at every handover**.
It is not the default beginner example. The generic examples use 60-second turns
and leave periodic BLE reset disabled. Each BMS exposes total voltage, current,
power, charging/discharging power, average cell voltage, two temperatures, SOC,
errors, online status and data age. Add further measurements using
[syssi's examples](https://github.com/syssi/esphome-jk-bms).

Only the gateway adds `Combined` aggregates for its two parallel 16-cell packs:
SUM of current and power (net, charging, discharging), AVG of SOC and average
cell voltage, MIN of minimum cell voltage, and MAX of maximum cell voltage.
SOC uses an unweighted mean for comparable capacities. Each aggregate requires
a finite stored value from every registered BMS for that measurement; otherwise
it is unavailable, never a partial sum. Values may come from different turns:
there is no age cutoff, and offline turns still use retained values. Check both
data-age sensors; aggregation does not make power integration more accurate.

## Operation and limitations

- The scheduler follows `rr_bms` in order and wraps around. All managed clients
  are disabled before a handover; a client is enabled only when BLE is active,
  not failed, and every managed client is `IDLE`.
- Declare each managed client with `auto_connect: false`. Do not add BLE switches
  or automations that enable clients outside the scheduler.
- Turn time and minimum dwell start at the **connection attempt**, not the first
  measurement. An offline BMS still loses its turn. Five 60-second turns mean
  roughly five minutes between visits, plus handover and scheduler delays.
- Numeric examples filter `NaN` to retain the last valid measurement during
  inactive turns. **Data Age** tracks the last finite raw voltage update, not
  merely an online event. Add the same filter to additional numeric measurements.
- Retained values are stale, not continuous live samples: do not use retained
  current/power as continuous input for energy calculations or critical controls.
  Binary sensors, switches and error text are not retained. Commands to inactive
  BMS are not queued.
- Values and counters live in RAM: reboot loses them; an API/Wi-Fi outage still
  makes the gateway unavailable in Home Assistant. Data Age is unavailable until
  the first valid measurement after boot.
- Data Age measures receipt of a valid BMS frame on the ESP32, even if values
  stay unchanged. Home Assistant state timestamps describe entity changes or
  reports there, not necessarily a fresh BMS frame; API reconnection can report
  retained values. No dedicated timer runs per BMS: age is calculated from a
  stored timestamp.
- Each configured client reserves a BLE slot, even while disabled. ESPHome
  currently allows up to nine slots; RAM and other BLE components may limit this.

### More or fewer BMS

Add/remove matching entries in `rr_bms`, `ble_client`, `jk_bms_ble`,
`binary_sensor`, `text_sensor`, and `sensor` (both measurements and data age).
Every client/online sensor must appear exactly once in the nonempty `rr_bms`
list. Timestamp indices in sensor lambdas are zero-based and must match that
list's order. No scheduler changes are needed.

## Settings

Override these substitutions in your device YAML. Durations use ESPHome syntax
(`5s`, `1500ms`); `_s` settings use integer seconds, up to 2147483.

| Setting | Package default | Purpose |
| --- | --- | --- |
| `rr_cycle_s` | `"60"` | Turn duration; positive integer seconds |
| `rr_min_dwell_s` | `"10"` | Minimum attempt time while online; `0` disables |
| `rr_check_interval` | `5s` | Scheduler check interval |
| `rr_disconnect_timeout` | `10s` | Wait for clients to reach IDLE |
| `rr_handover_delay` | `1s` | Settling delay before rechecking and enabling |
| `rr_reset_ble_on_handover` | `"false"` | Experimental full BLE reset each turn; enables disconnect-timeout escalation |
| `rr_ble_restart_timeout` | `15s` | Timeout per shutdown/startup phase |
| `rr_ble_off_delay` | `1s` | Pause between BLE shutdown and startup |
| `rr_disconnect_failures_before_recovery` | `"2"` | Consecutive disconnect timeouts before recovery with reset enabled; 1..100 |
| `rr_ble_recovery_attempts` | `"2"` | Maximum restart attempts, including the first; 1..10 |
| `rr_ble_recovery_delay` | `5s` | Pause before retrying a failed restart |
| `rr_reboot_on_recovery_failure` | `"false"` | Opt-in gateway reboot after exhausted recovery |

Example-only settings: `bms_throttle` defaults to `5s`;
the gateway's `rr_diagnostics_interval` defaults to `30s`.
Internal upstream BLE/protocol timeouts are unchanged.
Migrating from `rr_cycle_ms`/`rr_min_dwell_ms`: rename to `_s` and divide by 1000.

## Experimental recovery

Full-stack reset affects **all BLE functions** and can block the main loop for
about one second. Initial hardware tests avoided earlier HCI fragment warnings,
but do not prove a root-cause fix or long-term stability. The gateway with bounded
recovery and aggregates compiles with ESPHome 2026.9.0; timeout recovery and
aggregate behavior on the actual device still require hardware testing.

With reset enabled, repeated disconnect timeouts trigger recovery even if a
client is stuck outside IDLE; all clients remain disabled. Restart retries stop
after success or the configured limit. A BLE component marked failed cannot be
revived by normal BLE actions, so retries are skipped. An unavailable BLE host
requires recovery even when periodic reset is disabled.

Exhausted recovery logs an ERROR and suspends monitoring. Automatic reboot is
off by default; enabling it can cause repeated reboots under a persistent fault.
OTA stops handover and recovery; after an OTA error, pending recovery runs before
another client is enabled. Timeouts do not bound blocking inside ESPHome/ESP-IDF.

The gateway exposes uptime, free heap, largest free heap block, disconnect
timeouts, restart attempts and restart failures. Attempts include normal
handover restarts; failures count failed attempts, not OTA interruptions.
For a 24-48 hour test, compare heap at similar turn phases and watch both BMS'
data age. Short successful runs are not long-term stability evidence.

## Development

[Configuration tests](./tests/test_configurations.py) cover examples, device
counts, timing, retention and recovery structure:

```text
python -m unittest discover -s tests -v
git diff --check
```

Configuration validation and C++ generation do not replace firmware compilation
or BLE hardware tests. Never publish logs containing BMS passcodes or secrets.
