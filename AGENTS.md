# Project Guidelines

## Purpose and architecture

This repository provides a reusable ESPHome YAML package for sequential BLE
monitoring of multiple JK-BMS devices. It uses
[syssi/esphome-jk-bms](https://github.com/syssi/esphome-jk-bms) for the protocol
and entities; do not duplicate that component.

- [packages/round_robin.yaml](packages/round_robin.yaml) contains the shared
  scheduler. Users import it through ESPHome `packages`, not
  `external_components`.
- [examples/](examples/) contains device configurations. The
  [gateway example](examples/jk-bms-gateway.yaml) is a complete migration of the
  original installation and loads the package from GitHub.
- [README.md](README.md) describes setup, timing, limitations, and migration.

## Behavior to preserve

- Derive device count and polling order from `rr_bms`; never hard-code a
  two-device limit.
- Keep at most one managed BLE client enabled. Disable all managed clients and
  wait for their actual `IDLE` states before enabling the next client.
- On disconnect timeout, log an error and retry without enabling another
  client. An offline BMS must not block subsequent devices indefinitely.
- Prevent concurrent scheduler executions and pause connection attempts during
  OTA. Resume monitoring after an OTA error.
- Require `auto_connect: false` in managed client declarations to prevent
  connection races at boot. Do not expose controls that bypass the scheduler.
- Keep timing configurable in device YAML. `rr_cycle_s` and `rr_min_dwell_s`
  use integer seconds; other durations use ESPHome duration syntax. Preserve
  overflow guards and rollover-safe elapsed-time calculations.
- Minimum dwell currently starts at the connection attempt, not the online
  event. Do not change that meaning without documenting and testing migration.
- Preserve numeric NaN filters in examples and keep data age separate from
  online status. Only finite raw voltage updates refresh age; retained values
  and device-info responses are not fresh measurements.
- Keep the handover delay configurable and recheck `IDLE` after it. Treat it as
  a BLE settling measure, not a proven fix for HCI failures.

## Changes and user-facing configuration

- Keep scheduler logic shared; update affected examples, tests, and README
  together when configuration keys or behavior change.
- Preserve the gateway's device name, secret references, and entity names
  unless the requested change requires a migration.
- Prefer complete, ready-to-paste device configurations for Home Assistant
  ESPHome Device Builder users; avoid requiring unnecessary manual edits.
- Never commit real secrets, personal MAC addresses, or generated build files.
  Use dummy values in validation and do not flash hardware without approval.
- YAML packages have limited validation. Surface invalid inputs explicitly;
  do not silently report success or invent diagnostic percentages.

## Validation

Use a Python environment with ESPHome 2026.9.0 or newer installed.

```text
python -m unittest discover -s tests -v
git diff --check
```

[tests/test_configurations.py](tests/test_configurations.py) validates device
counts, timing overrides, and the gateway via ESPHome configuration validation
and C++ generation. Tests need GitHub access to fetch the upstream component.

For changes to C++ lambdas or BLE APIs, also compile an affected configuration
with `esphome compile <device.yaml>`, using dummy secrets outside the worktree.
Configuration validation and source generation are not proof of successful
compilation or reliable BLE operation. Report hardware testing separately.
Documentation-only changes do not require firmware builds.

## Publication

Commit, push, tag, or release only when requested. GitHub package examples need
the referenced code to be pushed before users can test them. After publication,
verify the remote package import, not only a substituted local copy.
Use immutable references for stable deployments; do not describe `main` as a
release. State clearly when a change exists only locally.
