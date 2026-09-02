#!/usr/bin/env bash
# Launch WOS-Bot Dashboard
PORT="${1:-8081}"
cd "$(dirname "$0")/.."
echo "❄️  Starting WOS-Bot Dashboard on http://localhost:$PORT"
uv run python -m dashboard.server --port "$PORT"
