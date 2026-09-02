"""
Unified configuration for WOS-Bot.
Loads from config/default.yaml with env var overrides.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "config" / "default.yaml"


@dataclass
class OCRConfig:
    host: str = "127.0.0.1"
    port: int = 8000
    timeout_sec: float = 8.0
    replay_wait_sec: float = 35.0
    replay_backoff_start_sec: float = 0.35
    replay_backoff_max_sec: float = 2.5
    ram_cap_gb: float = 3.0


@dataclass
class SchedulerConfig:
    skip_window_seconds: float = 3 * 60 * 60  # 3 hours default
    default_task_ttl_seconds: float = 3600.0
    max_retries_per_task: int = 2


@dataclass
class DeviceConfig:
    preferred_device_id: str | None = None
    screenshot_ttl: float = 0.1


@dataclass
class BotConfig:
    ocr: OCRConfig = field(default_factory=OCRConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    device: DeviceConfig = field(default_factory=DeviceConfig)
    project_root: Path = _PROJECT_ROOT
    references_dir: Path = _PROJECT_ROOT / "references"
    db_dir: Path = _PROJECT_ROOT / "db"

    @property
    def ocr_base_url(self) -> str:
        return f"http://{self.ocr.host}:{self.ocr.port}"

    @property
    def template_path(self) -> Path:
        return self.references_dir / "icon"

    @property
    def text_area_dir(self) -> Path:
        return self.references_dir / "TextArea"


def load_config(path: Path | None = None) -> BotConfig:
    """Load config from YAML file with env var overrides."""
    cfg = BotConfig()
    config_path = path or _CONFIG_PATH

    if config_path.exists():
        with open(config_path) as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}

        ocr = data.get("ocr", {})
        if "host" in ocr:
            cfg.ocr.host = ocr["host"]
        if "port" in ocr:
            cfg.ocr.port = int(ocr["port"])
        if "timeout_sec" in ocr:
            cfg.ocr.timeout_sec = float(ocr["timeout_sec"])
        if "replay_wait_sec" in ocr:
            cfg.ocr.replay_wait_sec = float(ocr["replay_wait_sec"])
        if "ram_cap_gb" in ocr:
            cfg.ocr.ram_cap_gb = float(ocr["ram_cap_gb"])

        sched = data.get("scheduler", {})
        if "skip_window_seconds" in sched:
            cfg.scheduler.skip_window_seconds = float(sched["skip_window_seconds"])
        if "default_task_ttl_seconds" in sched:
            cfg.scheduler.default_task_ttl_seconds = float(sched["default_task_ttl_seconds"])
        if "max_retries_per_task" in sched:
            cfg.scheduler.max_retries_per_task = int(sched["max_retries_per_task"])

        dev = data.get("device", {})
        if "preferred_device_id" in dev:
            cfg.device.preferred_device_id = dev["preferred_device_id"]

    # Env overrides always win
    if v := os.environ.get("OCR_PORT"):
        cfg.ocr.port = int(v)
    if v := os.environ.get("OCR_HOST"):
        cfg.ocr.host = v
    if v := os.environ.get("OCR_HTTP_TIMEOUT_SEC"):
        cfg.ocr.timeout_sec = float(v)
    if v := os.environ.get("OCR_REPLAY_WAIT_SEC"):
        cfg.ocr.replay_wait_sec = float(v)
    if v := os.environ.get("OCR_RAM_CAP_GB"):
        cfg.ocr.ram_cap_gb = float(v)
    if v := os.environ.get("WOS_DEVICE_ID"):
        cfg.device.preferred_device_id = v
    if v := os.environ.get("SKIP_WINDOW_SECONDS"):
        cfg.scheduler.skip_window_seconds = float(v)

    return cfg
