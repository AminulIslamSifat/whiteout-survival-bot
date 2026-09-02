"""
Calibration database: loads text areas and template configs.

Replaces the global text_area/template_area dicts from core/core.py.
Instance-scoped, supports device-specific overrides.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from config import BotConfig
from core.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class CalibrationDB:
    """Holds all text area ROIs and template match configs."""

    text_areas: dict[str, dict[str, Any]] = field(default_factory=dict)
    templates: dict[str, dict[str, Any]] = field(default_factory=dict)

    def get_text(self, name: str) -> Optional[dict[str, Any]]:
        return self.text_areas.get(name)

    def get_template(self, name: str) -> Optional[dict[str, Any]]:
        return self.templates.get(name)

    def get_text_box(self, name: str) -> Optional[list[float]]:
        entry = self.text_areas.get(name)
        if entry is None:
            return None
        return entry.get("box")

    def get_template_threshold(self, name: str, default: float = 0.8) -> float:
        entry = self.templates.get(name)
        if entry is None:
            return default
        return entry.get("threshold") or default

    def get_template_box(self, name: str) -> Optional[list[float]]:
        entry = self.templates.get(name)
        if entry is None:
            return None
        return entry.get("box")


def load_calibration(
    config: BotConfig,
    device_id: Optional[str] = None,
) -> CalibrationDB:
    """
    Load calibration data from references/.

    1. Load default text areas from references/TextArea/*.json
    2. Load template config from references/icon/template_config.json
    3. Override with device-specific calibration if available
    """
    db = CalibrationDB()

    # ── Text areas ───────────────────────────────────────────────────
    text_dir = config.text_area_dir
    if text_dir.exists():
        for f in sorted(text_dir.rglob("*.json")):
            if not f.is_file():
                continue
            try:
                with open(f) as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    db.text_areas.update(data)
                else:
                    logger.warning("Skipped non-dict file: %s", f)
            except Exception as e:
                logger.error("Error loading %s: %s", f, e)

    logger.info("📊 Loaded %d text areas", len(db.text_areas))

    # ── Templates ────────────────────────────────────────────────────
    template_config = config.template_path / "template_config.json"
    if template_config.exists():
        try:
            with open(template_config) as f:
                data = json.load(f)
            if isinstance(data, dict):
                db.templates = data
            logger.info("🖼️ Loaded %d template configs", len(db.templates))
        except Exception as e:
            logger.error("Error loading template config: %s", e)

    # ── Device-specific overrides ────────────────────────────────────
    if device_id:
        device_folder = config.references_dir / device_id
        if device_folder.exists():
            files = [
                f for f in device_folder.glob("*.json")
                if f.is_file() and not f.name.startswith("_")
            ]
            if files:
                logger.info("📱 Loading device-specific calibration for %s...", device_id)
                for f in files:
                    try:
                        with open(f) as fh:
                            data = json.load(fh)
                        if isinstance(data, dict):
                            old_count = len(db.text_areas)
                            db.text_areas.update(data)
                            new_items = len(db.text_areas) - old_count
                            logger.info("   ✅ %s: +%d items", f.name, new_items)
                    except Exception as e:
                        logger.warning("   ⚠️ Error loading %s: %s", f.name, e)

    return db
