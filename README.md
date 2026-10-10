# ESPHome JK-BMS BLE Round Robin

An ESPHome YAML package that connects one ESP32 sequentially to a configurable
list of JK-BMS devices. It is intended for installations where concurrent BLE
connections are unreliable.

The package builds on
[syssi/esphome-jk-bms](https://github.com/syssi/esphome-jk-bms); it provides
the connection scheduler, not a replacement for that component.

## Requirements

- ESPHome 2026.9.0 or newer, with ESP-IDF and a BLE-capable ESP32.
- One BLE client and one JK-BMS `online_status` binary sensor per BMS.
- `auto_connect: false` on every managed BLE client. This prevents concurrent
  connection attempts before the scheduler starts at boot.

## How it works

```text
    +-------------------------------------------------+
    |       ESPHOME BLE ROUND-ROBIN SCHEDULER         |
    +-------------------------------------------------+
                             |
    .------------------------▼------------------------.
    | 1. CONNECT FIRST BMS                            |
    |    - Connect to the first BMS in queue (BMS 1)  |
    |    - Ensure all other BLE clients are disabled  |
    '-------------------------------------------------'
                             |
    .------------------------▼------------------------.
    | 2. MONITOR (CYCLE TIME)                         |
    |    - Poll battery data via BLE                  |
    |    - Wait for configured cycle time (e.g. 60s)  |
    |    - Ensure min. dwell time is met              |
    '-------------------------------------------------'
                             |
    .------------------------▼------------------------.
    | 3. DISCONNECT & WAIT                            |
    |    - Turn off the active BLE client             |
    |    - Wait until BLE state is fully 'IDLE'       |
    |    - Wait configured handover delay             |
    '-------------------------------------------------'
                             |
    .------------------------▼------------------------.
    | 4. NEXT IN QUEUE                                |
    |    - Advance queue: BMS 1 (done) -> BMS 2       |
    '-------------------------------------------------'
                             |
                             \------------------------> (LOOP BACK TO 1.)
```

- Starts with the first entry in `rr_bms`, then visits every entry in order and
  wraps back to the first. Two, three, four, and five BMS use the same scheduler.
- Disables all managed clients before each handover and waits for all their BLE
  client states to become `IDLE`, rather than just checking a switch state.
- Waits an additional configurable `rr_handover_delay` after that check, then
  checks the states again before enabling the next client. This is a settling
  period, not a guarantee that ESP-IDF HCI errors are eliminated.
- Enables only the next client. If the disconnect timeout expires, it logs an
  error, leaves all clients disabled, and retries on the next scheduler check.
- Gives each BMS its configured cycle time. An offline BMS still loses its
  turn after that time, so it cannot block monitoring of the others.
- If the active BMS is online, also observes the configured minimum dwell time,
  measured from the **start of the connection attempt**, not the online event.
- Pauses the scheduler and disables all managed clients during OTA. After an OTA
  error, monitoring resumes with the interrupted BMS on the next check.

The BMS online-status sensors still reflect the upstream connection/data status.
The examples retain the last valid numeric measurements during an offline turn
and expose their data age; see below. This trades continuous monitoring for
sequential BLE polling.
With five BMS and 60-second turns, each BMS is visited about every five minutes,
plus handover time and scheduler-check granularity.

The scheduler has no hard-coded two-device limit. ESPHome/ESP-IDF still impose
BLE resource limits: the package sets `esp32_ble.max_connections` to the length
of `rr_bms`, because even disabled configured BLE clients consume reserved
slots. ESPHome currently allows up to nine slots; available RAM and other BLE
components may reduce practical capacity. Do not enable managed clients through
separate automations or BLE connection switches.

## Quick start

### Existing jk-bms-gateway installation

[`examples/jk-bms-gateway.yaml`](./examples/jk-bms-gateway.yaml) is a complete
replacement configuration for the original two-BMS gateway. Paste its entire
contents into the existing device in ESPHome Device Builder. It loads the
scheduler from GitHub using `packages`, not `external_components`, so no local
package file is needed. The upstream JK-BMS component still comes from syssi.
ESPHome 2026.9.0 or newer is required.

It retains the device name, ESP32 board, protocol, main and backup Wi-Fi secret
names, BMS MAC secret names, and all JK-BMS measurement/control entity names.
The manual handover button now calls the shared scheduler. Direct BLE connection
switches are intentionally omitted to prevent bypassing the single-client
invariant. The original success-rate sensor is omitted because its failure
counter was never incremented, making its percentage misleading.

The gateway example uses 90-second turns for both BMS instead of the package's
60-second default, allowing more time for a slower handshake and data transfer.
It keeps BMS 300 in the normal rotation. The handover delay defaults to one
second. Both values are configurable.

All examples pin syssi's component to a previously validated commit instead of
following `main`, so BLE tests use reproducible upstream code. UART logging is
disabled (`baud_rate: 0`); API logs remain available. JK-BMS and measurement
logging is reduced to `WARN` to avoid verbose frame dumps and limit logging
overhead. Scheduler INFO messages and BLE warnings/errors remain visible.

This test configuration follows `main` and refreshes the package on each build.
The repository must be pushed before using it remotely. A release is not needed
for testing; use an immutable tag or commit as `ref` for a stable deployment
after hardware verification.

### Generic installations

1. Copy [`examples/two-bms.yaml`](./examples/two-bms.yaml) or
   [`examples/five-bms.yaml`](./examples/five-bms.yaml), together with
   [`packages/round_robin.yaml`](./packages/round_robin.yaml), into your ESPHome
   configuration directory, preserving the relative paths.
2. Add `wifi_ssid`, `wifi_password`, and `bms1_mac_address` through
   `bmsN_mac_address` to the `secrets.yaml` used by your chosen example:

   ```yaml
   wifi_ssid: "your-wifi"
   wifi_password: "your-password"
   bms1_mac_address: "AA:BB:CC:DD:EE:01"
   bms2_mac_address: "AA:BB:CC:DD:EE:02"
   bms3_mac_address: "AA:BB:CC:DD:EE:03"
   bms4_mac_address: "AA:BB:CC:DD:EE:04"
   bms5_mac_address: "AA:BB:CC:DD:EE:05"
   ```

3. Adapt the board, Wi-Fi, and protocol version. The examples use `esp32dev`,
   ESP-IDF, and `JK02_32S`.
4. Configure the BMS list and timing in the device YAML's `substitutions`:

   ```yaml
   substitutions:
     rr_bms:
       - client: rr_client_bms1
         online: rr_bms1_online
       - client: rr_client_bms2
         online: rr_bms2_online
       - client: rr_client_bms3
         online: rr_bms3_online
     rr_cycle_s: "60"
     rr_min_dwell_s: "10"
     rr_check_interval: 5s
     rr_disconnect_timeout: 10s
     rr_handover_delay: 1s
     bms_throttle: 5s
   ```

5. Add the sensors, switches, and buttons you need using syssi's `jk_bms_ble`
   platforms, then validate and install with ESPHome.

## Adding or removing BMS

For each device, declare a `ble_client` with `auto_connect: false`, a
`jk_bms_ble` instance referencing that client, and an `online_status` sensor.
Add the client ID and online sensor ID as one entry in `rr_bms`. IDs are
user-defined; their spelling does not determine the polling order.

To use three or four devices, remove the unused entries from the five-BMS
example's `rr_bms`, `ble_client`, `jk_bms_ble`, `binary_sensor`, and `sensor` lists
(remove both the unused BMS measurements and their data-age diagnostics).
No scheduler changes are needed. Every managed client and online sensor must
appear exactly once in `rr_bms`, and the list must not be empty.
The zero-based indices used by measurement callbacks and data-age lambdas must
match the corresponding BMS positions in `rr_bms`. Update these indices if you
reorder or remove entries from the middle of the list.

## Retained measurements and data age

The upstream JK-BMS component publishes `NaN` when it marks a device unavailable.
Each numeric BMS measurement in the examples uses `filters: - filter_out: nan`
to drop those updates and retain the last valid value in Home Assistant.
Apply the same filter to any additional numeric BMS sensors you add. The gateway
example covers all its original numeric measurements; the generic examples show
total voltage. Binary sensors, control switches, and error text are not filtered
or artificially kept online.

Every example also includes a `Data Age` diagnostic per BMS, in seconds. A
finite **raw total-voltage update** records a timestamp in the package's
`rr_last_data_us` vector. NaN updates and online/device-info events do not refresh
that timestamp. Total voltage is a representative cell-info measurement, not
proof that every individual sensor was updated. Age uses the ESP32 monotonic
64-bit timer, so it does not wrap with `millis()` after approximately 49 days.

Before the first valid voltage update after boot, age is unavailable. While a
BMS is disconnected or failing to return measurements, age keeps increasing
and its numeric measurements retain their last values. There is no automatic
staleness cutoff in this version: use data age when deciding whether retained
values are suitable for dashboards or automations. Do not treat retained power
or current as a continuous live sample for energy calculations or controls.

Retention is in ESPHome's RAM, not persistent storage. It does not preserve
measurements through a gateway reboot or keep entities available when Home
Assistant loses the gateway's API connection. The filter does not add repeated
measurement publications; only actual valid updates are forwarded.

## Timing settings

| Substitution | Default | Meaning |
| --- | --- | --- |
| `rr_cycle_s` | `"60"` | Time per BMS connection attempt, in seconds; positive integer |
| `rr_min_dwell_s` | `"10"` | Minimum time since attempt start while online, in seconds; zero disables it |
| `rr_check_interval` | `5s` | Scheduler evaluation interval; positive ESPHome duration |
| `rr_disconnect_timeout` | `10s` | Maximum wait for all clients to become idle; positive ESPHome duration |
| `rr_handover_delay` | `1s` | Additional settling time after an idle check, before rechecking and enabling the next client |
| `bms_throttle` | `5s` | Upstream JK-BMS update throttle used by the examples |

The package supplies defaults for all `rr_` timing settings; override them in
the device YAML. A handover occurs on the first check after the cycle time and,
if online, the minimum dwell time have elapsed. Second settings must be
integer literals no larger than 2147483; they are converted to milliseconds
internally, and elapsed-time subtraction handles
`millis()` rollover.

When upgrading from the previous millisecond settings, replace `rr_cycle_ms`
with `rr_cycle_s` and `rr_min_dwell_ms` with `rr_min_dwell_s`, dividing the values
by 1000 (for example, `"60000"` becomes `"60"`). The old keys are no longer used.

These settings control this package and the example's update throttle. Internal
BLE/protocol timeouts in ESPHome and the upstream JK-BMS component are not
changed by this package. Firmware compilation and hardware testing are required
before deploying a changed device count or timing configuration.

## Configuration tests

With ESPHome 2026.9.0 or newer installed in your Python environment, run:

```text
python -m unittest discover -s tests -v
```

The tests validate the examples, configurations with three, four, and five BMS,
timing overrides, NaN filters, data-age wiring, and reduced logging using
ESPHome's configuration validation and C++ source generation. They use dummy
secrets in temporary directories and do not flash hardware or replace a
firmware compile or BLE hardware test.
