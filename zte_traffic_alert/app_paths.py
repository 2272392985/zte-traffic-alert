from __future__ import annotations

import os
from pathlib import Path
import platform
import shutil
import sys


APP_DIR_NAME = "ZTE Traffic Alert"


def bundled_config_example_path() -> Path:
    bundle_root = getattr(sys, "_MEIPASS", "")
    if bundle_root:
        return Path(bundle_root) / "config.example.json"
    return Path(__file__).resolve().parents[1] / "config.example.json"


def default_gui_config_path() -> Path:
    system = platform.system()
    if system == "Darwin":
        config_dir = Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    elif system == "Windows":
        appdata = os.environ.get("APPDATA")
        config_dir = Path(appdata) / APP_DIR_NAME if appdata else Path.home() / APP_DIR_NAME
    else:
        config_dir = Path.home() / ".config" / "zte-traffic-alert"

    try:
        config_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        config_dir = Path.cwd()

    config_path = config_dir / "config.json"
    if not config_path.exists():
        example_path = bundled_config_example_path()
        if example_path.exists():
            try:
                shutil.copyfile(example_path, config_path)
            except OSError:
                pass
    return config_path
