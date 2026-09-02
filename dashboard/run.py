#!/usr/bin/env python3
"""Launch WOS-Bot Dashboard."""
import sys
import logging
from pathlib import Path

# Add project root to sys.path so 'dashboard' package is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import os
os.chdir(PROJECT_ROOT)

port = int(sys.argv[1]) if len(sys.argv) > 1 else 8081

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-7s │ %(name)s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)
logger.info("❄️  Starting WOS-Bot Dashboard on http://localhost:%d", port)

import uvicorn
from dashboard.server import app

uvicorn.run(app, host="0.0.0.0", port=port, timeout_graceful_shutdown=1)
