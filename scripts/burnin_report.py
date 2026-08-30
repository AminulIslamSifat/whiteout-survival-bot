"""Vision-swap burn-in verdict from logs/ocr_burnin.jsonl.

Exit criteria (docs/designs/vision-ocr-swap.md):
  - >= 7 days elapsed AND >= 2000 distinct expectation-carrying decisions
    (expected_text or read_kind=value; retries share a decision_id),
    capped at 14 days: past the cap, decide on available data.
  - fallback rate < 1% of value-read decisions (labels never fall back)
  - zero unwaived DIGIT_MISMATCH decisions
    (waive by listing decision_ids, one per line, in logs/burnin_waivers.txt)
  - RSS growth: last-day median - first-day median < 200 MB

Usage: uv run python scripts/burnin_report.py [path-to-jsonl]
"""
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

DAY_S = 86400.0
MIN_DAYS = 7
CAP_DAYS = 14
MIN_DECISIONS = 2000
MAX_FALLBACK_RATE = 0.01
MAX_RSS_GROWTH_MB = 200.0


def load_records(path):
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # torn write at process kill; skip
    return records


def load_waivers(path):
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text().splitlines() if line.strip()}


def compute_verdict(records, waivers=frozenset(), now=None):
    """Pure verdict computation — unit-testable. Returns a dict."""
    if not records:
        return {"verdict": "NO DATA", "reasons": ["burn-in log is empty"]}

    first_ts = min(r["ts"] for r in records)
    last_ts = max(r["ts"] for r in records)
    days = (last_ts - first_ts) / DAY_S

    def is_expectation(r):
        return bool(r.get("expected")) or r.get("read_kind") == "value"

    exp_decisions = {}
    for r in records:
        if not is_expectation(r):
            continue
        d = exp_decisions.setdefault(r.get("decision_id") or "unknown", {
            "fallback": False, "mismatch": False, "value": False,
        })
        if r.get("fallback_hits"):
            d["fallback"] = True
        if r.get("digit_mismatch"):
            d["mismatch"] = True
        if r.get("read_kind") == "value":
            d["value"] = True

    n_decisions = len(exp_decisions)
    value_decisions = sum(1 for d in exp_decisions.values() if d["value"])
    n_fallback = sum(1 for d in exp_decisions.values() if d["fallback"])
    mismatched = [k for k, d in exp_decisions.items() if d["mismatch"]]
    unwaived = [k for k in mismatched if k not in waivers]
    fallback_rate = (n_fallback / value_decisions) if value_decisions else 0.0

    by_day = {}
    for r in records:
        day = datetime.fromtimestamp(r["ts"], tz=timezone.utc).date().isoformat()
        if "rss_mb" in r:
            by_day.setdefault(day, []).append(r["rss_mb"])
    day_medians = {d: statistics.median(v) for d, v in sorted(by_day.items())}
    if len(day_medians) >= 2:
        vals = list(day_medians.values())
        rss_growth_mb = vals[-1] - vals[0]
    else:
        rss_growth_mb = 0.0

    volume_ok = n_decisions >= MIN_DECISIONS
    duration_ok = days >= MIN_DAYS
    capped = days >= CAP_DAYS

    criteria_failures = []
    if fallback_rate >= MAX_FALLBACK_RATE:
        criteria_failures.append(
            f"fallback rate {fallback_rate:.2%} >= {MAX_FALLBACK_RATE:.0%} "
            "-> reopen the template-digit fallback decision"
        )
    if unwaived:
        criteria_failures.append(
            f"{len(unwaived)} unwaived DIGIT_MISMATCH decisions: {unwaived[:5]}"
        )
    if rss_growth_mb >= MAX_RSS_GROWTH_MB:
        criteria_failures.append(
            f"RSS growth {rss_growth_mb:.0f}MB >= {MAX_RSS_GROWTH_MB:.0f}MB "
            "-> reinstate RAM-cap machinery on the vision path"
        )

    progress_shortfalls = []
    if not duration_ok:
        progress_shortfalls.append(f"only {days:.1f}/{MIN_DAYS} days elapsed")
    if not volume_ok:
        progress_shortfalls.append(
            f"only {n_decisions}/{MIN_DECISIONS} expectation-carrying decisions"
        )

    reasons = criteria_failures + progress_shortfalls
    if criteria_failures:
        verdict = ("EXIT: FAIL (14-day cap reached with failing criteria)"
                   if capped else "IN PROGRESS")
    elif not duration_ok or (not volume_ok and not capped):
        verdict = "IN PROGRESS"
    elif not volume_ok and capped:
        verdict = "EXIT: DECIDE ON AVAILABLE DATA (14-day cap reached, volume short)"
    else:
        verdict = "EXIT: PASS — burn-in complete; reopen the Paddle-removal decision"

    return {
        "verdict": verdict,
        "reasons": reasons,
        "days": round(days, 2),
        "decisions": n_decisions,
        "value_decisions": value_decisions,
        "fallback_rate": round(fallback_rate, 4),
        "mismatched": mismatched,
        "unwaived_mismatches": unwaived,
        "rss_growth_mb": round(rss_growth_mb, 1),
        "rss_day_medians": day_medians,
        "total_reads": len(records),
    }


def main():
    log_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("logs/ocr_burnin.jsonl")
    if not log_path.exists():
        print(f"no burn-in log at {log_path}")
        return 1
    waivers = load_waivers(log_path.parent / "burnin_waivers.txt")
    result = compute_verdict(load_records(log_path), waivers)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
