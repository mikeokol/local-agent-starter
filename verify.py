#!/usr/bin/env python3
"""verify.py — judge the starter's report against the fixture ground truth.

Ground truth is read fresh from the fixture files (not hardcoded): the
verification code from the element with id 'target' in page1.html, the
arrival text from the element with id 'arrival' in page2.html. Same
check shape as the trial's Leg 3 verdict
(`'PLATYPUS-4721' in final_result and 'page two' in final_result`),
but the expected strings come from the fixture, so a changed fixture
still verifies correctly.

Usage:
    python3 verify.py                       # checks runs/latest/report.md
    python3 verify.py --report runs/x/report.md

Exit 0 PASS, 1 FAIL (or report missing).
"""

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE_DIR = os.path.join(HERE, "fixture")


def element_text(html, element_id):
    m = re.search(rf'id="{re.escape(element_id)}"[^>]*>([^<]+)<', html)
    return m.group(1).strip() if m else None


def code_token(target_text):
    """The verification code is the code-like token inside the target
    element (e.g. PLATYPUS-4721), not the whole sentence around it."""
    m = re.search(r"[A-Z]{2,}[A-Z0-9]*-[0-9]+", target_text)
    return m.group(0) if m else target_text


def check_report(report_path):
    """Deterministic completion check, importable by the agent loop.

    Returns (ok, missing, detail). `missing` names the unmet criteria in
    plain words ('report missing', 'verification code', 'arrival text');
    `detail` carries the ground-truth strings and what was found.
    Ground truth is read fresh from the fixture files, never hardcoded.
    """
    try:
        with open(os.path.join(FIXTURE_DIR, "page1.html")) as f:
            target = element_text(f.read(), "target")
        with open(os.path.join(FIXTURE_DIR, "page2.html")) as f:
            arrival = element_text(f.read(), "arrival")
    except OSError as e:
        return False, ["ground truth unreadable"], {
            "error": f"ground truth unreadable: {e}"}
    if target is None or arrival is None:
        return False, ["ground truth not found in fixture files"], {
            "error": "ground truth not found in fixture files"}
    code = code_token(target)
    if not os.path.exists(report_path):
        return False, ["report missing"], {
            "code": code, "arrival": arrival}
    with open(report_path) as f:
        report = f.read()
    # Token match, not substring: 'PLATYPUS-4721' must not match inside
    # 'PLATYPUS-47210' (M5-L3, continuous-sandbox 2026-11-19 — the
    # substring form let a longer token satisfy the finish gate). The
    # arrival text is a full sentence, so a substring match is the
    # right check for it: the sentence itself is the fact.
    has_code = re.search(
        rf"(?<![A-Za-z0-9-]){re.escape(code)}(?![A-Za-z0-9-])",
        report) is not None
    has_arrival = arrival in report
    missing = []
    if not has_code:
        missing.append("verification code")
    if not has_arrival:
        missing.append("arrival text")
    return (not missing), missing, {
        "code": code, "arrival": arrival,
        "has_code": has_code, "has_arrival": has_arrival}


def main():
    ap = argparse.ArgumentParser(description="verify the starter report")
    ap.add_argument("--report",
                    default=os.path.join(HERE, "runs", "latest", "report.md"))
    args = ap.parse_args()

    ok, missing, detail = check_report(args.report)
    if "error" in detail:
        print(f"VERIFY ERROR: {detail['error']}")
        return 1
    if missing == ["report missing"]:
        print(f"FAIL: report missing: {args.report}")
        return 1
    code, arrival = detail["code"], detail["arrival"]
    print(f"ground truth code:    {code!r} -> {'FOUND' if detail['has_code'] else 'MISSING'}")
    print(f"ground truth arrival: {arrival!r} -> {'FOUND' if detail['has_arrival'] else 'MISSING'}")
    if ok:
        print("VERDICT: PASS — report contains both required facts")
        return 0
    print("VERDICT: FAIL — report is missing a required fact")
    return 1


if __name__ == "__main__":
    sys.exit(main())
