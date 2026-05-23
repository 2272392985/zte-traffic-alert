import tempfile
import unittest
from pathlib import Path

from zte_traffic_alert.config import ActionConfig, AppConfig, ServiceConfig, TrafficConfig
from zte_traffic_alert.service import TrafficAlertService


class FakeClient:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.disconnect_called = False

    def get_traffic(self, _config):
        return self.snapshot

    def disconnect(self):
        self.disconnect_called = True
        return {"result": "success"}


class Snapshot:
    rx_bytes = 95 * 1024**3
    tx_bytes = 4 * 1024**3
    used_bytes = 99 * 1024**3
    rx_field = "monthly_rx_bytes"
    tx_field = "monthly_tx_bytes"


class TrafficAlertServiceTest(unittest.TestCase):
    def test_threshold_triggers_dry_run(self):
        with tempfile.TemporaryDirectory() as directory:
            config = AppConfig(
                traffic=TrafficConfig(plan_gb=100, disconnect_when_remaining_gb_lte=2),
                service=ServiceConfig(
                    poll_interval_seconds=300,
                    state_path=str(Path(directory) / "state.json"),
                    log_path="",
                ),
                action=ActionConfig(mode="dry_run"),
            )
            service = TrafficAlertService(config)
            service.client = FakeClient(Snapshot())

            result = service.check_once()

            self.assertTrue(result.ok)
            self.assertTrue(result.triggered)
            self.assertEqual(result.action, "dry_run")

    def test_non_triggered_check_clears_previous_trigger_state(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state_path.write_text('{"threshold_triggered": true}', encoding="utf-8")
            config = AppConfig(
                traffic=TrafficConfig(plan_gb=300, disconnect_when_remaining_gb_lte=2),
                service=ServiceConfig(
                    poll_interval_seconds=300,
                    state_path=str(state_path),
                    log_path="",
                ),
                action=ActionConfig(mode="dry_run"),
            )
            service = TrafficAlertService(config)
            service.client = FakeClient(Snapshot())

            result = service.check_once()

            self.assertTrue(result.ok)
            self.assertFalse(result.triggered)
            self.assertIn('"threshold_triggered": false', state_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
