"""Client-side decision-id / read_kind plumbing (core/core.py req_ocr).

Every OCR request must carry a decision_id — a fresh UUID when the caller
doesn't pass one, the caller's shared id when it does (tap_on_text passes one
id across its retried reads so burn-in rates count decisions, not attempts).
read_kind must reach the server payload untouched: the server's zero-item
fallback and shadow-compare key on it.
"""
import core.core as cc


def _capture_payloads(monkeypatch):
    payloads = []

    def fake_post(url, payload, request_name, wait_sec=None):
        payloads.append(payload)
        return {"success": True, "count": 0, "results": []}

    monkeypatch.setattr(cc, "_post_json_with_replay", fake_post)
    return payloads


def test_auto_decision_ids_are_fresh_per_call(monkeypatch):
    payloads = _capture_payloads(monkeypatch)
    cc.req_ocr(name="a")
    cc.req_ocr(name="b")
    ids = [p["decision_id"] for p in payloads]
    assert all(ids), "every request must carry a decision_id"
    assert ids[0] != ids[1], "unrelated calls must not share a decision"


def test_explicit_decision_id_and_read_kind_pass_through(monkeypatch):
    payloads = _capture_payloads(monkeypatch)
    cc.req_ocr(name="a", read_kind="value", decision_id="shared-1")
    assert payloads[0]["decision_id"] == "shared-1"
    assert payloads[0]["read_kind"] == "value"


def test_read_kind_defaults_to_none_for_label_reads(monkeypatch):
    payloads = _capture_payloads(monkeypatch)
    cc.req_ocr(name="a", expected_text="Read & Claim")
    assert payloads[0]["read_kind"] is None
    assert payloads[0]["expected_text"] == "Read & Claim"
