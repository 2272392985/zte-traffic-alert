import argparse
import json
import sys

from .config import load_config
from .router import ZTERouterClient
from .service import TrafficAlertService, configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="zte_traffic_alert",
        description="Monitor ZTE pocket WiFi traffic and disconnect when quota is low.",
    )
    parser.add_argument("--config", default="config.json", help="Path to JSON config file.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("diagnose", help="Print raw traffic API values.")
    subparsers.add_parser("once", help="Run one check and exit.")
    subparsers.add_parser("run", help="Run forever until interrupted.")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(args.config)
    configure_logging(config.service.log_path)

    if args.command == "diagnose":
        client = ZTERouterClient(config.router)
        payload = client.diagnose()
        print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    service = TrafficAlertService(config)
    if args.command == "once":
        result = service.check_once()
        print(result.summary())
        return 0 if result.ok else 2

    if args.command == "run":
        return service.run_forever()

    print(f"Unknown command: {args.command}", file=sys.stderr)
    return 2

