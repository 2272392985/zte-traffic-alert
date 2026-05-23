from __future__ import annotations

from dataclasses import dataclass
from http.cookiejar import CookieJar
import hashlib
import json
import re
import time
from typing import Any
from urllib import parse, request

from .config import RouterConfig, TrafficConfig


COMMON_TRAFFIC_FIELDS = [
    "monthly_rx_bytes",
    "monthly_tx_bytes",
    "total_rx_bytes",
    "total_tx_bytes",
    "realtime_rx_bytes",
    "realtime_tx_bytes",
    "data_volume_used",
    "traffic_used",
]

RX_FIELD_CANDIDATES = {
    "monthly": ["monthly_rx_bytes", "month_rx_bytes", "rx_month_bytes", "total_rx_bytes"],
    "total": ["total_rx_bytes", "all_rx_bytes", "rx_bytes", "monthly_rx_bytes"],
}

TX_FIELD_CANDIDATES = {
    "monthly": ["monthly_tx_bytes", "month_tx_bytes", "tx_month_bytes", "total_tx_bytes"],
    "total": ["total_tx_bytes", "all_tx_bytes", "tx_bytes", "monthly_tx_bytes"],
}


@dataclass(frozen=True)
class TrafficSnapshot:
    rx_bytes: int
    tx_bytes: int
    used_bytes: int
    raw: dict[str, Any]
    rx_field: str
    tx_field: str


class RouterApiError(RuntimeError):
    pass


class ZTERouterClient:
    def __init__(self, config: RouterConfig):
        self.config = config
        self.base_url = config.base_url.rstrip("/")
        self.cookie_jar = CookieJar()
        self.opener = request.build_opener(request.HTTPCookieProcessor(self.cookie_jar))
        self.request_token = ""
        self.logged_in = False

    def diagnose(self) -> dict[str, Any]:
        payload = self.get_cmd(COMMON_TRAFFIC_FIELDS + ["LD", "network_type", "loginfo"])
        return {
            "base_url": self.base_url,
            "known_fields": {key: payload.get(key) for key in COMMON_TRAFFIC_FIELDS if key in payload},
            "raw": payload,
        }

    def get_traffic(self, traffic_config: TrafficConfig) -> TrafficSnapshot:
        fields = self._wanted_fields(traffic_config)
        payload = self.get_cmd(fields)

        if traffic_config.rx_field and traffic_config.tx_field:
            rx_field = traffic_config.rx_field
            tx_field = traffic_config.tx_field
        else:
            mode = traffic_config.counter_mode.lower()
            rx_field = self._first_present(payload, RX_FIELD_CANDIDATES.get(mode, []))
            tx_field = self._first_present(payload, TX_FIELD_CANDIDATES.get(mode, []))

        if not rx_field or not tx_field:
            raise RouterApiError(
                "Could not find RX/TX traffic fields. Run diagnose and set "
                "traffic.rx_field / traffic.tx_field in config.json."
            )

        rx_bytes = parse_byte_value(payload.get(rx_field))
        tx_bytes = parse_byte_value(payload.get(tx_field))
        return TrafficSnapshot(
            rx_bytes=rx_bytes,
            tx_bytes=tx_bytes,
            used_bytes=rx_bytes + tx_bytes,
            raw=payload,
            rx_field=rx_field,
            tx_field=tx_field,
        )

    def disconnect(self) -> dict[str, Any]:
        self.login_if_needed()
        errors = []
        for goform_id in self.config.disconnect_goform_ids:
            try:
                response = self.post_goform({"goformId": goform_id})
            except Exception as exc:
                errors.append(f"{goform_id}: {exc}")
                continue
            result = str(response.get("result", "")).lower()
            if result in {"0", "success", "ok", "true"}:
                return {"goformId": goform_id, "response": response}
            if "result" not in response and response:
                return {"goformId": goform_id, "response": response}
            errors.append(f"{goform_id}: {response}")
        raise RouterApiError("All disconnect attempts failed: " + "; ".join(errors))

    def login_if_needed(self) -> None:
        if self.logged_in or not self.config.admin_password:
            return

        ld_payload = self.get_cmd(["LD"])
        ld_value = str(ld_payload.get("LD", ""))
        password = self.config.admin_password
        hashed_password = hashlib.sha256((password + ld_value).encode("utf-8")).hexdigest()
        response = self.post_goform({"goformId": "LOGIN", "password": hashed_password})
        result = str(response.get("result", "")).lower()
        if result not in {"0", "success", "ok", "true"}:
            fallback = self.post_goform({"goformId": "LOGIN", "password": password})
            fallback_result = str(fallback.get("result", "")).lower()
            if fallback_result not in {"0", "success", "ok", "true"}:
                raise RouterApiError(f"Router login failed: {response}")
        self.logged_in = True

    def get_cmd(self, commands: list[str]) -> dict[str, Any]:
        query = {
            "isTest": "false",
            "cmd": ",".join(commands),
            "multi_data": "1",
            "_": str(int(time.time() * 1000)),
        }
        url = f"{self.base_url}/goform/goform_get_cmd_process?{parse.urlencode(query)}"
        return self._json_request("GET", url)

    def post_goform(self, data: dict[str, str]) -> dict[str, Any]:
        url = f"{self.base_url}/goform/goform_set_cmd_process"
        payload = {"isTest": "false", **data}
        return self._json_request("POST", url, payload)

    def _json_request(
        self, method: str, url: str, form: dict[str, str] | None = None
    ) -> dict[str, Any]:
        body = None
        headers = {
            "User-Agent": "zte-traffic-alert/0.1",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": f"{self.base_url}/index.html",
            "X-Requested-With": "XMLHttpRequest",
        }
        if self.request_token:
            headers["__RequestVerificationToken"] = self.request_token
        if form is not None:
            body = parse.urlencode(form).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"

        req = request.Request(url, data=body, headers=headers, method=method)
        try:
            with self.opener.open(req, timeout=self.config.request_timeout_seconds) as response:
                self._capture_token(response.headers)
                raw = response.read().decode("utf-8", errors="replace")
        except Exception as exc:
            raise RouterApiError(f"Router request failed: {method} {url}: {exc}") from exc

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RouterApiError(f"Router returned non-JSON response: {raw[:200]}") from exc
        if not isinstance(parsed, dict):
            raise RouterApiError(f"Router returned unexpected JSON: {parsed!r}")
        return parsed

    def _capture_token(self, headers) -> None:
        for key in (
            "__RequestVerificationToken",
            "__RequestVerificationTokenone",
            "__RequestVerificationTokentwo",
        ):
            value = headers.get(key)
            if value:
                self.request_token = value
                return

    def _wanted_fields(self, traffic_config: TrafficConfig) -> list[str]:
        fields = set(COMMON_TRAFFIC_FIELDS)
        mode = traffic_config.counter_mode.lower()
        fields.update(RX_FIELD_CANDIDATES.get(mode, []))
        fields.update(TX_FIELD_CANDIDATES.get(mode, []))
        if traffic_config.rx_field:
            fields.add(traffic_config.rx_field)
        if traffic_config.tx_field:
            fields.add(traffic_config.tx_field)
        return sorted(fields)

    @staticmethod
    def _first_present(payload: dict[str, Any], fields: list[str]) -> str:
        for field in fields:
            if field in payload and payload[field] not in ("", None):
                return field
        return ""


def parse_byte_value(value: Any) -> int:
    if value is None or value == "":
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().replace(",", "")
    if text.isdigit():
        return int(text)

    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*([KMGT]?I?B?)", text, re.IGNORECASE)
    if not match:
        raise RouterApiError(f"Cannot parse byte value: {value!r}")

    number = float(match.group(1))
    unit = match.group(2).upper()
    multipliers = {
        "": 1,
        "B": 1,
        "K": 1024,
        "KB": 1024,
        "KIB": 1024,
        "M": 1024**2,
        "MB": 1024**2,
        "MIB": 1024**2,
        "G": 1024**3,
        "GB": 1024**3,
        "GIB": 1024**3,
        "T": 1024**4,
        "TB": 1024**4,
        "TIB": 1024**4,
    }
    return int(number * multipliers[unit])
