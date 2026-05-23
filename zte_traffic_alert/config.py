from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RouterConfig:
    base_url: str = "http://192.168.0.1"
    admin_password: str = ""
    request_timeout_seconds: int = 8
    disconnect_goform_ids: list[str] = field(
        default_factory=lambda: ["DISCONNECT_NETWORK", "DISCONNECT"]
    )


@dataclass(frozen=True)
class TrafficConfig:
    plan_gb: float = 100.0
    unit: str = "GiB"
    disconnect_when_remaining_gb_lte: float = 2.0
    rx_field: str = ""
    tx_field: str = ""
    counter_mode: str = "monthly"


@dataclass(frozen=True)
class ServiceConfig:
    poll_interval_seconds: int = 300
    state_path: str = "zte_traffic_alert_state.json"
    log_path: str = "zte_traffic_alert.log"


@dataclass(frozen=True)
class ActionConfig:
    mode: str = "dry_run"
    repeat_disconnect: bool = False
    local_command: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AppConfig:
    router: RouterConfig = field(default_factory=RouterConfig)
    traffic: TrafficConfig = field(default_factory=TrafficConfig)
    service: ServiceConfig = field(default_factory=ServiceConfig)
    action: ActionConfig = field(default_factory=ActionConfig)


def _section(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"Config section '{key}' must be an object.")
    return value


def _clean_dataclass_kwargs(cls, values: dict[str, Any]) -> dict[str, Any]:
    allowed = set(cls.__dataclass_fields__.keys())
    return {key: value for key, value in values.items() if key in allowed}


def _normalize_traffic_config(values: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(values)
    if "plan_gb" not in normalized and "plan_gib" in normalized:
        normalized["plan_gb"] = normalized["plan_gib"]
    if (
        "disconnect_when_remaining_gb_lte" not in normalized
        and "alert_when_remaining_gib_lte" in normalized
    ):
        normalized["disconnect_when_remaining_gb_lte"] = normalized[
            "alert_when_remaining_gib_lte"
        ]
    return normalized


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file not found: {config_path}. Copy config.example.json first."
        )

    with config_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError("Config root must be a JSON object.")

    config = AppConfig(
        router=RouterConfig(**_clean_dataclass_kwargs(RouterConfig, _section(data, "router"))),
        traffic=TrafficConfig(
            **_clean_dataclass_kwargs(
                TrafficConfig, _normalize_traffic_config(_section(data, "traffic"))
            )
        ),
        service=ServiceConfig(
            **_clean_dataclass_kwargs(ServiceConfig, _section(data, "service"))
        ),
        action=ActionConfig(**_clean_dataclass_kwargs(ActionConfig, _section(data, "action"))),
    )
    validate_config(config)
    return config


def validate_config(config: AppConfig) -> None:
    if config.traffic.plan_gb <= 0:
        raise ValueError("traffic.plan_gb must be greater than 0.")
    if config.traffic.disconnect_when_remaining_gb_lte < 0:
        raise ValueError("traffic.disconnect_when_remaining_gb_lte must not be negative.")
    if config.service.poll_interval_seconds < 10:
        raise ValueError("service.poll_interval_seconds must be at least 10.")
    if config.action.mode not in {"dry_run", "router_disconnect", "local_command"}:
        raise ValueError("action.mode must be dry_run, router_disconnect, or local_command.")
    if config.action.mode == "local_command" and not config.action.local_command:
        raise ValueError("action.local_command must be set when action.mode is local_command.")
    unit = config.traffic.unit.upper()
    if unit not in {"GIB", "GB"}:
        raise ValueError("traffic.unit must be GiB or GB.")


def plan_bytes(config: TrafficConfig) -> int:
    unit = config.unit.upper()
    multiplier = 1024**3 if unit == "GIB" else 1000**3
    return int(config.plan_gb * multiplier)


def threshold_bytes(config: TrafficConfig) -> int:
    multiplier = 1024**3 if config.unit.upper() == "GIB" else 1000**3
    return int(config.disconnect_when_remaining_gb_lte * multiplier)
