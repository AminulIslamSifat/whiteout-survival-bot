"""
WOS-Bot Entry Point

Replaces Main/main.py. Supports:
- CLI: python run_bot.py --tasks=vip,arena,gather --device=DEVICE_ID
- Stdin JSON: {"tasks": [...], "accounts": [...], "characters": {...}}
- Multi-device: --device can be specified multiple times or auto-detected

Each device runs in its own thread with isolated DeviceContext.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import load_config
from core.logging_config import get_logger
from device.adb import list_adb_devices
from bot.runner import BotRunner

logger = get_logger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="WOS-Bot Runner")
    parser.add_argument(
        "--tasks", type=str,
        help="Comma-separated task keys (e.g., vip,arena,gather)",
    )
    parser.add_argument(
        "--device", type=str, action="append",
        help="ADB device ID (can be specified multiple times for multi-device)",
    )
    parser.add_argument(
        "--config", type=str, default=None,
        help="Path to config YAML file",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    # Load config
    config_path = Path(args.config) if args.config else None
    config = load_config(config_path)

    # Determine task keys + optional filters
    task_keys: list[str] = []
    account_filter: list[str] | None = None
    character_filter: dict[str, list[str]] | None = None

    if args.tasks:
        task_keys = [k.strip() for k in args.tasks.split(",") if k.strip()]
    elif not sys.stdin.isatty():
        try:
            raw = sys.stdin.read().strip()
            if raw:
                data = json.loads(raw)
                if isinstance(data, dict) and "tasks" in data:
                    task_keys = data["tasks"]
                    account_filter = data.get("accounts")
                    character_filter = data.get("characters")
                elif isinstance(data, list):
                    task_keys = data
        except (json.JSONDecodeError, Exception) as e:
            logger.error("Failed to parse stdin JSON: %s", e)
            sys.exit(1)

    if not task_keys:
        logger.error("No tasks specified. Use --tasks=key1,key2 or pipe JSON via stdin.")
        sys.exit(1)

    # Determine devices
    device_ids: list[str] = []
    if args.device:
        device_ids = args.device
    elif config.device.preferred_device_id:
        device_ids = [config.device.preferred_device_id]
    else:
        device_ids = list_adb_devices()
        if not device_ids:
            logger.error("❌ No ADB devices found. Connect a device or specify --device.")
            sys.exit(1)

    logger.info("📱 Devices: %s", ", ".join(device_ids))
    logger.info("🎯 Tasks: %s", ", ".join(task_keys))
    if account_filter:
        logger.info("📧 Account filter: %s", ", ".join(account_filter))

    # Sync resolution for first device (backward compat)
    from core.coord_utils import set_base_resolution
    try:
        from device.adb import DeviceContext
        first_device = DeviceContext(device_ids[0])
        w, h = first_device.screen_size
        set_base_resolution(w, h)
        logger.info("✅ Coordinate system synchronized: %d×%d", w, h)
    except Exception as e:
        logger.warning("⚠️ Could not sync resolution: %s", e)

    # Launch one runner per device
    if len(device_ids) == 1:
        # Single device: run in main thread
        runner = BotRunner(
            device_ids[0], config, task_keys,
            account_filter=account_filter,
            character_filter=character_filter,
        )
        runner.run()
    else:
        # Multi-device: one thread per device
        threads: list[threading.Thread] = []
        for dev_id in device_ids:
            runner = BotRunner(
                dev_id, config, task_keys,
                account_filter=account_filter,
                character_filter=character_filter,
            )
            t = threading.Thread(target=runner.run, name=f"bot-{dev_id}", daemon=True)
            threads.append(t)
            t.start()
            logger.info("🚀 Started bot thread for %s", dev_id)

        # Wait for all threads
        try:
            for t in threads:
                t.join()
        except KeyboardInterrupt:
            logger.info("⏹ Interrupted. Stopping all bots...")


if __name__ == "__main__":
    main()
