"""Burn-in verdict math on synthetic ledgers (scripts/burnin_report.py)."""
import time

import pytest

from scripts.burnin_report import compute_verdict, DAY_S


NOW = time.time()


def _read(day, decision, *, kind="value", fallback=0, mismatch=False, rss=400.0,
          expected=False):
    return {
        "ts": NOW - (10 - day) * DAY_S,
        "decision_id": decision,
        "read_kind": kind,
        "expected": expected,
        "fallback_hits": fallback,
        "digit_mismatch": mismatch,
        "rss_mb": rss,
    }


def _healthy_week(n_decisions=2500):
    records = []
    for i in range(n_decisions):
        day = i % 8  # spread across 8 days
        records.append(_read(day, f"d{i}"))
    return records


class TestExitCriteria:
    def test_healthy_week_passes(self):
        r = compute_verdict(_healthy_week())
        assert r["verdict"].startswith("EXIT: PASS")
        assert r["reasons"] == []

    def test_empty_log(self):
        assert compute_verdict([])["verdict"] == "NO DATA"

    def test_too_few_days_in_progress(self):
        records = [_read(day=8, decision=f"d{i}") for i in range(3000)]
        records += [_read(day=9, decision=f"e{i}") for i in range(10)]
        r = compute_verdict(records)
        assert r["verdict"] == "IN PROGRESS"
        assert any("days elapsed" in s for s in r["reasons"])

    def test_too_few_decisions_in_progress(self):
        records = [_read(day=i % 8, decision=f"d{i}") for i in range(100)]
        r = compute_verdict(records)
        assert r["verdict"] == "IN PROGRESS"
        assert any("decisions" in s for s in r["reasons"])

    def test_retries_collapse_into_one_decision(self):
        # 3000 reads but only 30 distinct decision ids.
        records = [_read(day=i % 8, decision=f"d{i % 30}") for i in range(3000)]
        r = compute_verdict(records)
        assert r["decisions"] == 30
        assert r["total_reads"] == 3000

    def test_expectation_free_reads_excluded_from_denominator(self):
        records = _healthy_week()
        records += [_read(day=i % 8, decision=f"free{i}", kind=None) for i in range(500)]
        r = compute_verdict(records)
        assert r["decisions"] == 2500

    def test_expected_text_reads_count_as_expectation(self):
        records = [_read(day=i % 8, decision=f"d{i}", kind=None, expected=True)
                   for i in range(2500)]
        r = compute_verdict(records)
        assert r["decisions"] == 2500


class TestFailureCriteria:
    def test_fallback_rate_over_one_percent_fails(self):
        records = _healthy_week(2000)
        records += [_read(day=i % 8, decision=f"fb{i}", fallback=1) for i in range(30)]
        r = compute_verdict(records)
        assert any("template-digit" in s for s in r["reasons"])

    def test_unwaived_mismatch_blocks(self):
        records = _healthy_week()
        records.append(_read(day=3, decision="bad1", mismatch=True))
        r = compute_verdict(records)
        assert any("DIGIT_MISMATCH" in s for s in r["reasons"])

    def test_waived_mismatch_does_not_block(self):
        records = _healthy_week()
        records.append(_read(day=3, decision="bad1", mismatch=True))
        r = compute_verdict(records, waivers={"bad1"})
        assert r["verdict"].startswith("EXIT: PASS")
        assert r["mismatched"] == ["bad1"] and r["unwaived_mismatches"] == []

    def test_rss_growth_fails(self):
        records = []
        for i in range(2500):
            day = i % 8
            records.append(_read(day, f"d{i}", rss=300.0 + day * 40))  # +280MB across window
        r = compute_verdict(records)
        assert any("RSS growth" in s for s in r["reasons"])
        assert any("RAM-cap" in s for s in r["reasons"])


class TestFourteenDayCap:
    def test_cap_reached_low_volume_decides_on_data(self):
        records = [_read(day=0, decision=f"d{i}") for i in range(50)]
        records += [_read(day=10, decision=f"e{i}") for i in range(50)]
        # spread first/last 15 days apart
        records[0]["ts"] = NOW - 15 * DAY_S
        r = compute_verdict(records)
        assert "14-day cap" in r["verdict"]
