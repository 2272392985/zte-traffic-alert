from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import subprocess
import time
from typing import Any

from .config import AppConfig, plan_bytes, threshold_bytes
from .router import TrafficSnapshot, ZTERouterClient


LOGGER = logging.getLogger("zte_traffic_alert")


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    used_bytes: int = 0
    remaining_bytes: int = 0
    triggered: bool = False
    action: str = ""
    message: str = ""

    def summary(self) -> str:
        if not self.ok:
            return f"ERROR: {self.message}"
        return (
            f"used={format_gib(self.used_bytes)}, "
            f"remaining={format_gib(self.remaining_bytes)}, "
            f"triggered={self.triggered}, action={self.action or 'none'}"
        )


class TrafficAlertService:
    def __init__(self, config: AppConfig):
        self.config = config
        self.client = ZTERouterClient(config.router)
        self.state_path = Path(config.service.state_path)

    def run_forever(self) -> int:
        LOGGER.info("ZTE traffic alert service started")
        while True:
            result = self.check_once()
            if result.ok:
                LOGGER.info(result.summary())
            else:
                LOGGER.error(result.summary())
            time.sleep(self.config.service.poll_interval_seconds)

    def check_once(self) -> CheckResult:
        try:
            snapshot = self.client.get_traffic(self.config.traffic)
            state = self._load_state()
            result = self._evaluate(snapshot, state)
            self._save_state(snapshot, result, state)
            return result
        except Exception as exc:
            LOGGER.exception("Check failed")
            return CheckResult(ok=False, message=str(exc))

    def _evaluate(self, snapshot: TrafficSnapshot, state: dict[str, Any]) -> CheckResult:
        quota = plan_bytes(self.config.traffic)
        threshold = threshold_bytes(self.config.traffic)
        remaining = max(quota - snapshot.used_bytes, 0)
        already_triggered = bool(state.get("threshold_triggered"))
        should_trigger = remaining <= threshold

        LOGGER.debug(
            "Traffic fields rx=%s tx=%s used=%s remaining=%s threshold=%s",
            snapshot.rx_field,
            snapshot.tx_field,
            snapshot.used_bytes,
            remaining,
            threshold,
        )

        if not should_trigger:
            return CheckResult(ok=True, used_bytes=snapshot.used_bytes, remaining_bytes=remaining)

        if already_triggered and not self.config.action.repeat_disconnect:
            return CheckResult(
                ok=True,
                used_bytes=snapshot.used_bytes,
                remaining_bytes=remaining,
                triggered=True,
                action="already_triggered",
            )

        action = self._perform_action()
        return CheckResult(
            ok=True,
            used_bytes=snapshot.used_bytes,
            remaining_bytes=remaining,
            triggered=True,
            action=action,
        )

    def _perform_action(self) -> str:
        mode = self.config.action.mode
        if mode == "dry_run":
            LOGGER.warning("Threshold reached; dry_run mode, no disconnect executed")
            return "dry_run"
        if mode == "router_disconnect":
            response = self.client.disconnect()
            LOGGER.warning("Threshold reached; router disconnect response: %s", response)
            return "router_disconnect"
        if mode == "local_command":
            subprocess.run(self.config.action.local_command, check=True)
            LOGGER.warning("Threshold reached; local command executed")
            return "local_command"
        raise ValueError(f"Unsupported action mode: {mode}")

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {}
        with self.state_path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}

    def _save_state(
        self,
        snapshot: TrafficSnapshot,
        result: CheckResult,
        previous_state: dict[str, Any],
    ) -> None:
        state = dict(previous_state)
        state.update(
            {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "used_bytes": snapshot.used_bytes,
                "remaining_bytes": result.remaining_bytes,
                "rx_field": snapshot.rx_field,
                "tx_field": snapshot.tx_field,
            }
        )
        if result.triggered:
            state["threshold_triggered"] = True
            state["last_triggered_at"] = datetime.now(timezone.utc).isoformat()
            state["last_action"] = result.action
        elif state.get("threshold_triggered"):
            state["threshold_triggered"] = False
        elif snapshot.used_bytes < int(previous_state.get("used_bytes", 0)):
            state["threshold_triggered"] = False

        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with self.state_path.open("w", encoding="utf-8") as file:
            json.dump(state, file, indent=2, ensure_ascii=False, sort_keys=True)


def configure_logging(log_path: str) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_path:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


def format_gib(value: int) -> str:
    return f"{value / 1024**3:.2f} GiB"
