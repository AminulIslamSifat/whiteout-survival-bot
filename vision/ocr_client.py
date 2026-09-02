"""
HTTP client for the OCR microservice.

Stateless — no globals. Takes base_url from config.
All methods return parsed JSON or None on failure.
Includes exponential-backoff replay for service recovery.
"""

from __future__ import annotations

import time
from typing import Any, Optional

import requests

from config import BotConfig
from core.logging_config import get_logger

logger = get_logger(__name__)


class OCRClient:
    """HTTP client for the PaddleOCR FastAPI service."""

    def __init__(self, config: BotConfig) -> None:
        self._base_url = config.ocr_base_url
        self._timeout = config.ocr.timeout_sec
        self._replay_wait = config.ocr.replay_wait_sec
        self._backoff_start = config.ocr.replay_backoff_start_sec
        self._backoff_max = config.ocr.replay_backoff_max_sec

    @property
    def ocr_url(self) -> str:
        return f"{self._base_url}/ocr"

    @property
    def template_url(self) -> str:
        return f"{self._base_url}/template"

    @property
    def cache_clear_url(self) -> str:
        return f"{self._base_url}/clear_cache"

    @property
    def health_url(self) -> str:
        return f"{self._base_url}/health"

    # ── Public API ───────────────────────────────────────────────────

    def is_healthy(self) -> bool:
        """Check if OCR service is responding."""
        try:
            resp = requests.get(self.health_url, timeout=2)
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def request_ocr(
        self,
        *,
        img_path: Optional[str] = None,
        save_result: Optional[bool] = None,
        rois: Optional[list[list[int]]] = None,
        name: Optional[str] = None,
        expected_text: Optional[str] = None,
    ) -> Optional[list[dict[str, Any]]]:
        """Send OCR request and return results list."""
        payload: dict[str, Any] = {
            "img_path": img_path,
            "save_result": save_result,
            "rois": rois,
            "name": name,
            "expected_text": expected_text,
        }
        data = self._post_with_replay(self.ocr_url, payload, f"OCR:{name}")
        if not data:
            return None
        return data.get("results")

    def request_template_match(
        self,
        name: str,
        *,
        threshold: float = 0.8,
        save_result: Optional[bool] = None,
        rois: Optional[list[list[int]]] = None,
        parallel: Optional[bool] = None,
        session_id: Optional[str] = None,
    ) -> Optional[list[dict[str, Any]]]:
        """Send template match request and return results list."""
        payload: dict[str, Any] = {
            "name": name,
            "threshold": threshold,
            "save_result": save_result,
            "rois": rois,
            "parallel": parallel,
            "session_id": session_id,
        }
        data = self._post_with_replay(self.template_url, payload, f"Template:{name}")
        if not data:
            return None
        return data.get("results")

    def clear_cache(self, session_id: str) -> None:
        """Clear server-side screenshot cache for a session."""
        try:
            requests.post(
                self.cache_clear_url,
                json={"session_id": session_id},
                timeout=self._timeout,
            )
        except requests.RequestException as e:
            logger.warning("Cache clear skipped (OCR unavailable): %s", e)

    # ── Internal ─────────────────────────────────────────────────────

    def _post_with_replay(
        self,
        url: str,
        payload: dict[str, Any],
        request_name: str,
    ) -> Optional[dict[str, Any]]:
        """POST with exponential backoff until success or timeout."""
        start = time.time()
        attempt = 0
        backoff = self._backoff_start

        while True:
            attempt += 1
            try:
                response = requests.post(url, json=payload, timeout=self._timeout)
                response.raise_for_status()
                data = response.json()

                if isinstance(data, dict) and data.get("success") is True:
                    return data

                err = data.get("error") if isinstance(data, dict) else "non-dict response"
                logger.warning("%s attempt %d returned failure: %s", request_name, attempt, err)

            except (requests.RequestException, ValueError) as e:
                logger.error("%s attempt %d failed: %s", request_name, attempt, e)

            elapsed = time.time() - start
            if elapsed >= self._replay_wait:
                logger.error("%s replay timed out after %.1fs", request_name, elapsed)
                return None

            time.sleep(backoff)
            backoff = min(backoff * 2, self._backoff_max)
