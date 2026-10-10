import copy
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


class ValidatedLoader(yaml.SafeLoader):
    pass


ValidatedLoader.add_constructor(
    "!lambda", lambda loader, node: loader.construct_scalar(node)
)


def load_example(path: Path) -> dict:
    class Loader(yaml.SafeLoader):
        pass

    def include(loader: Loader, node: yaml.ScalarNode) -> dict:
        return load_example(path.parent / loader.construct_scalar(node))

    def secret(loader: Loader, node: yaml.ScalarNode) -> str:
        name = loader.construct_scalar(node)
        if name in ("bms200_mac_address", "bms300_mac_address"):
            return {"bms200_mac_address": "AA:BB:CC:DD:EE:01",
                    "bms300_mac_address": "AA:BB:CC:DD:EE:02"}[name]
        if name.endswith("_mac_address"):
            index = int(name.removeprefix("bms").removesuffix("_mac_address"))
            return f"AA:BB:CC:DD:EE:{index:02X}"
        return {
            "wifi_ssid": "test-network",
            "wifi_password": "test-password",
            "wifi_backup_ssid": "test-backup",
            "wifi_backup_password": "test-backup-password",
        }[name]

    Loader.add_constructor("!include", include)
    Loader.add_constructor("!secret", secret)
    return yaml.load(path.read_text(encoding="utf-8"), Loader=Loader)


class ConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workspace = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.workspace.cleanup()

    def validate(self, config: dict) -> tuple[dict, str]:
        directory = Path(self.workspace.name)
        path = directory / "test.yaml"
        path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        results = []
        for arguments in (["config"], ["compile", "--only-generate"]):
            result = subprocess.run(
                [sys.executable, "-m", "esphome", *arguments, str(path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                env={**os.environ, "PYTHONUTF8": "1"},
                timeout=120,
            )
            self.assertEqual(
                result.returncode, 0, result.stdout + result.stderr
            )
            results.append(result.stdout)
        source = (
            directory
            / ".esphome"
            / "build"
            / config["substitutions"]["name"]
            / "src"
            / "main.cpp"
        ).read_text(encoding="utf-8")
        return yaml.load(results[0], Loader=ValidatedLoader), source

    def test_two_bms_example(self) -> None:
        config, source = self.validate(load_example(ROOT / "examples" / "two-bms.yaml"))
        self.assertEqual(config["esp32_ble"]["max_connections"], 2)
        self.assertIn("% rr_clients->value().size()", source)

    def test_existing_gateway(self) -> None:
        config = load_example(ROOT / "examples" / "jk-bms-gateway.yaml")
        config["packages"]["round_robin"] = load_example(
            ROOT / "packages" / "round_robin.yaml"
        )
        validated, source = self.validate(config)
        self.assertEqual(validated["esphome"]["name"], "jk-bms-gateway")
        self.assertEqual(len(validated["wifi"]["networks"]), 2)
        self.assertEqual(len(validated["sensor"]), 9)
        self.assertEqual(len(validated["switch"]), 2)
        self.assertEqual(validated["debug"]["update_interval"], "30s")
        diagnostics = {
            sensor["name"] for sensor in validated["sensor"]
            if sensor["platform"] in ("template", "uptime")
        }
        self.assertTrue({
            "Gateway Uptime", "BLE Disconnect Timeouts",
            "BLE Restart Attempts", "BLE Restart Failures",
        }.issubset(diagnostics))
        self.assertIn("client_200, client_300", source)

    def test_three_four_and_five_bms(self) -> None:
        example = load_example(ROOT / "examples" / "five-bms.yaml")
        for count in (3, 4, 5):
            with self.subTest(count=count):
                config = copy.deepcopy(example)
                config["substitutions"]["rr_bms"] = config["substitutions"]["rr_bms"][:count]
                for key in ("ble_client", "jk_bms_ble", "binary_sensor"):
                    config[key] = config[key][:count]
                config["sensor"] = config["sensor"][:count] + config["sensor"][5:5 + count]
                validated, source = self.validate(config)
                self.assertEqual(validated["esp32_ble"]["max_connections"], count)
                self.assertEqual(len(validated["ble_client"]), count)
                self.assertEqual(len(validated["binary_sensor"]), count)
                self.assertEqual(len(validated["sensor"]), count * 2)
                self.assertIn(f"rr_client_bms{count}", source)
                self.assertNotIn(f"rr_client_bms{count + 1}", source)
                expected_clients = ", ".join(
                    f"rr_client_bms{index}" for index in range(1, count + 1)
                )
                self.assertIn(
                    f"rr_clients->value() = {{{expected_clients}}};", source
                )

    def test_custom_timing(self) -> None:
        config = load_example(ROOT / "examples" / "five-bms.yaml")
        config["substitutions"].update(
            rr_cycle_s="23",
            rr_min_dwell_s="37",
            rr_check_interval="2s",
            rr_disconnect_timeout="7s",
            rr_handover_delay="1500ms",
            bms_throttle="3s",
        )
        validated, source = self.validate(config)
        self.assertEqual(validated["interval"][0]["interval"], "2s")
        self.assertTrue(all(bms["throttle"] == "3s" for bms in validated["jk_bms_ble"]))
        self.assertIn("elapsed < 23 * 1000UL", source)
        self.assertIn("elapsed >= 37 * 1000UL", source)
        self.assertRegex(
            source, re.compile(r"set_timeout_value\(.*?return 7000;", re.DOTALL)
        )
        self.assertRegex(
            source, re.compile(r"set_delay\(.*?return 1500;", re.DOTALL)
        )

    def test_package_timing_defaults(self) -> None:
        config = load_example(ROOT / "examples" / "two-bms.yaml")
        for setting in (
            "rr_cycle_s", "rr_min_dwell_s", "rr_check_interval", "rr_disconnect_timeout",
            "rr_handover_delay",
        ):
            del config["substitutions"][setting]
        validated, source = self.validate(config)
        self.assertEqual(validated["interval"][0]["interval"], "5s")
        self.assertIn("elapsed < 60 * 1000UL", source)
        self.assertIn("elapsed >= 10 * 1000UL", source)
        self.assertRegex(
            source, re.compile(r"set_timeout_value\(.*?return 10000;", re.DOTALL)
        )
        self.assertRegex(
            source, re.compile(r"set_delay\(.*?return 1000;", re.DOTALL)
        )

    def test_retention_and_data_age(self) -> None:
        for filename, count in (
            ("two-bms.yaml", 2), ("five-bms.yaml", 5), ("jk-bms-gateway.yaml", 2)
        ):
            with self.subTest(example=filename):
                config = load_example(ROOT / "examples" / filename)
                if filename == "jk-bms-gateway.yaml":
                    config["packages"]["round_robin"] = load_example(
                        ROOT / "packages" / "round_robin.yaml"
                    )
                validated, source = self.validate(config)
                measurements = [
                    sensor for sensor in validated["sensor"]
                    if sensor["platform"] == "jk_bms_ble"
                ]
                for index, measurement in enumerate(measurements):
                    for key, sensor in measurement.items():
                        if key in ("platform", "jk_bms_ble_id"):
                            continue
                        self.assertTrue(math.isnan(sensor["filters"][0]["filter_out"]))
                    update = measurement["total_voltage"]["on_raw_value"][0]["then"][0]["lambda"]
                    self.assertIn("std::isfinite(x)", update)
                    self.assertIn(f"id(rr_last_data_us)[{index}] = esp_timer_get_time()", update)
                ages = [
                    sensor for sensor in validated["sensor"]
                    if sensor["platform"] == "template" and sensor["name"].endswith(" Data Age")
                ]
                self.assertEqual(len(ages), count)
                for index, age in enumerate(ages):
                    self.assertEqual(age["unit_of_measurement"], "s")
                    self.assertIn(f"id(rr_last_data_us)[{index}]", age["lambda"])
                    self.assertIn("last == 0 ? NAN", age["lambda"])
                self.assertIn("left IDLE during handover delay", source)
                self.assertIn(f"std::vector<int64_t>({count}, 0)", source)
                self.assertEqual(validated["logger"]["baud_rate"], 0)
                self.assertEqual(validated["logger"]["logs"]["jk_bms_ble"], "WARN")

    def test_handover_guards(self) -> None:
        package = load_example(ROOT / "packages" / "round_robin.yaml")
        actions = package["script"][0]["then"][0]["if"]["then"]
        self.assertIn("wait_until", actions[1])
        self.assertIn("rr_disconnect_timeouts", actions[2]["lambda"])
        branch = actions[3]["if"]
        self.assertIn("rr_disconnect_failures_before_recovery", branch["condition"]["lambda"])
        restart = branch["then"][0]["if"]["then"]
        self.assertEqual(restart[0]["script.execute"], "rr_restart_ble_stack")
        self.assertEqual(restart[1]["script.wait"], "rr_restart_ble_stack")
        self.assertEqual(branch["then"][1]["delay"], "${rr_handover_delay}")
        enable = branch["then"][2]["lambda"]
        self.assertLess(enable.index("ClientState::IDLE"), enable.index("set_enabled(true)"))
        self.assertLess(enable.index("is_active()"), enable.index("set_enabled(true)"))
        self.assertIn("id(rr_suspended)", enable)
        self.assertEqual(branch["else"][0]["logger.log"]["level"], "ERROR")
        ota_start = package["ota"][0]["on_begin"]["then"]
        self.assertEqual(ota_start[1]["script.stop"], "rr_switch_connection")
        self.assertEqual(ota_start[2]["script.stop"], "rr_restart_ble_stack")
        self.assertIn("rr_ble_recovery_required", actions[1]["wait_until"]["condition"]["lambda"])

    def test_bounded_ble_recovery(self) -> None:
        package = load_example(ROOT / "packages" / "round_robin.yaml")
        recovery = package["script"][1]["then"]
        repeat = recovery[1]["repeat"]
        self.assertEqual(repeat["count"], "${rr_ble_recovery_attempts}")
        attempt = repeat["then"][0]["if"]
        self.assertIn("!id(rr_ble_restart_ready)", attempt["condition"]["lambda"])
        self.assertIn("is_failed()", attempt["condition"]["lambda"])
        retry_delay = attempt["then"][0]["if"]
        self.assertIn("rr_ble_recovery_attempt) > 0", retry_delay["condition"]["lambda"])
        self.assertEqual(retry_delay["then"][0]["delay"], "${rr_ble_recovery_delay}")
        self.assertIn("ble.disable", attempt["then"][2])
        self.assertEqual(attempt["then"][3]["wait_until"]["timeout"], "${rr_ble_restart_timeout}")
        startup = attempt["then"][4]["if"]["then"]
        self.assertEqual(startup[0]["delay"], "${rr_ble_off_delay}")
        self.assertIn("ble.enable", startup[1])
        self.assertEqual(startup[2]["wait_until"]["timeout"], "${rr_ble_restart_timeout}")
        self.assertIn("ClientState::IDLE", startup[3]["lambda"])
        self.assertIn("id(rr_ble_recovery_required) = false", startup[3]["lambda"])
        exhausted = recovery[2]["if"]["then"]
        self.assertIn("id(rr_suspended) = true", exhausted[0]["lambda"])
        reboot = exhausted[1]["if"]
        self.assertEqual(reboot["condition"]["lambda"], "return ${rr_reboot_on_recovery_failure};")
        self.assertEqual(reboot["then"][1]["button.press"], "rr_reboot_gateway")
        self.assertEqual(package["substitutions"]["rr_reboot_on_recovery_failure"], "false")
        self.assertTrue(package["button"][0]["internal"])

    def test_custom_ble_recovery_timing(self) -> None:
        config = load_example(ROOT / "examples" / "two-bms.yaml")
        config["substitutions"].update(
            rr_reset_ble_on_handover="true",
            rr_disconnect_failures_before_recovery="3",
            rr_ble_recovery_attempts="3",
            rr_ble_recovery_delay="7s",
            rr_ble_restart_timeout="11s",
            rr_ble_off_delay="2s",
            rr_reboot_on_recovery_failure="true",
        )
        validated, source = self.validate(config)
        recovery = validated["script"][1]["then"][1]["repeat"]
        self.assertEqual(recovery["count"], 3)
        self.assertIn("rr_disconnect_failures->value() >= 3", source)
        for duration in (7000, 2000):
            self.assertRegex(
                source, re.compile(rf"set_delay\(.*?return {duration};", re.DOTALL)
            )
        self.assertRegex(
            source, re.compile(r"set_timeout_value\(.*?return 11000;", re.DOTALL)
        )


if __name__ == "__main__":
    unittest.main()
