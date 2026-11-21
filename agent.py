#!/usr/bin/env python3
"""local-agent starter — a small tool-using agent loop on a local Ollama model.

Assembled from existing pieces (see RECEIPT.md); no new framework, no new
dependency — Python 3 standard library only, talking to Ollama's HTTP API.

THE TASK (default): read the Leg-3 fixture's two pages, extract the
verification code from page 1 and the arrival text from page 2, and write
a report containing both. Same goal the browser-use agent failed on
Nov 16, done by a loop designed to survive this box's limits.

WHY THIS LOOP IS SHAPED THE WAY IT IS (all from the author's unpublished
trial notes — Qwen trial, November 2026):
- qwen3:8b thinks by default; a 1000+ token thinking trace at ~2 tok/s
  takes 10-20 min per step and blew browser-use's 300 s deadline three
  times (Leg 3: 0 steps completed). So every call here sets "think": false
  and caps output at ~220 tokens: one short JSON action per step.
- The runner was SIGKILLed 7 times in the trial, with 6.1-6.3 GiB free —
  not host OOM, cause undetermined. So each step is written to an
  append-only JSONL trace the moment it completes (the trial's per-sample
  record lesson), and a failed generation retries once, then stops with
  a recorded failure instead of crashing silently.
- The ctx2k variant halves the KV cache vs the 4096 default, restoring
  load headroom on the 7.7 GB box. The model default is qwen3:8b-ctx2k;
  num_ctx 2048 is also passed per-request, so the loop survives even if
  the tag is missing and qwen3:8b is used instead.
- The box's bracketed-IPv6 no_proxy breaks httpx URL parsing (Leg 1
  false start). This script uses urllib with proxies disabled outright
  for loopback calls, so the proxy env cannot touch it.

AUTHORITY SHAPE (pattern, not integration): before any tool runs, the
proposed action goes through check_action() — an allowlist + path
confinement check with a logged verdict, in the shape of Alfred's
execution adapter (author's local file, not in this repo). The
adapter itself is NOT called: it judges Alfred's mandate scopes, which
are not this agent's. The loop only ever reads inside the fixture dir
and writes inside its own run dir; anything else is DENIED and the
denial is fed back to the model as the observation.

Every write_file goes through ledger.py (per-action ledger with inverses,
recorded in the run dir as ledger.jsonl); --rollback undoes a run's
recorded actions from the ledger alone.

Usage:
    python3 agent.py                       # live run, default task/out dir
    python3 agent.py --dry-run             # stub model, no Ollama needed
    python3 agent.py --model qwen3:8b      # different model tag
    python3 agent.py --steps 6 --out-dir runs/test-1
    python3 agent.py --rollback --out-dir runs/test-1   # undo the run

Exit codes: 0 finished (report written AND verified against the fixture
ground truth by the finish check inside the loop),
1 max steps reached without finishing, 2 model/server failure after
retry, 3 usage error.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from ledger import Ledger, RollbackError
from verify import check_report
FIXTURE_DIR = os.path.join(HERE, "fixture")
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
DEFAULT_MODEL = "qwen3:8b-ctx2k"
MAX_PROMPT_CHARS = 6000  # transcript guard: keep the prompt inside ctx2k
CALL_TIMEOUT_S = 900     # per-call ceiling; a short action needs ~25-75 s

SYSTEM = (
    "You are a local file agent. Each turn, output exactly one JSON object "
    "and no other text. Allowed actions:\n"
    '{"action": "read_file", "path": "<path>"} — read a text file.\n'
    '{"action": "list_dir", "path": "<path>"} — list a directory.\n'
    '{"action": "write_file", "path": "<path>", "content": "<text>"} — '
    "write a text file.\n"
    '{"action": "finish", "summary": "<one sentence>"} — end the task.\n'
    "Read only inside the fixture directory. Write only inside the run "
    "directory. Keep every output short."
)

# No-proxy opener: loopback calls must never touch the box's broken proxy env.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def mem_available_mb():
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        pass
    return None


def check_action(action, out_dir):
    """Deterministic pre-action check. Returns (verdict, reason).

    Verdicts mirror the execution adapter's shape: ALLOW / DENY.
    The model proposes; this function judges, and never trusts the
    proposal's own framing.
    """
    if not isinstance(action, dict) or "action" not in action:
        return "DENY", "not a JSON action object"
    kind = action["action"]
    if kind == "finish":
        return "ALLOW", "finish"
    if kind not in ("read_file", "list_dir", "write_file"):
        return "DENY", f"unknown action class: {kind!r}"
    path = action.get("path")
    if not isinstance(path, str) or not path:
        return "DENY", "missing path"
    real = os.path.realpath(os.path.expanduser(path))
    if kind in ("read_file", "list_dir"):
        if os.path.commonpath([real, os.path.realpath(FIXTURE_DIR)]) != \
                os.path.realpath(FIXTURE_DIR) and \
                os.path.commonpath([real, os.path.realpath(HERE)]) != \
                os.path.realpath(HERE):
            return "DENY", f"read outside fixture/starter dirs: {path}"
    if kind == "write_file":
        if os.path.commonpath([real, os.path.realpath(out_dir)]) != \
                os.path.realpath(out_dir):
            return "DENY", f"write outside run dir: {path}"
        if os.path.basename(real).lower() in ("trace.jsonl", "ledger.jsonl"):
            return "DENY", ("write to the run's own evidence file is "
                            "forbidden by name: "
                            f"{os.path.basename(real)}")
        if not isinstance(action.get("content"), str):
            return "DENY", "write_file needs a string content field"
    return "ALLOW", "allowlisted action, path inside its confinement"


def run_tool(action, out_dir, ledger=None):
    kind = action["action"]
    path = os.path.expanduser(action["path"])
    if kind == "read_file":
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        return f"read {path} ({len(text)} chars):\n{text[:2000]}"
    if kind == "list_dir":
        names = sorted(os.listdir(path))
        return f"listing {path}: {', '.join(names)}"
    if kind == "write_file":
        content = action["content"]
        if ledger is not None:
            # Writes go through the ledger: it performs the write, then
            # records it with its inverse, so the run's actions can be
            # rolled back from the ledger alone.
            entry = ledger.record_write(
                path, content.encode("utf-8"), note="write_file")
            return (f"wrote {path} ({len(content)} chars) "
                    f"[ledger seq {entry['seq']}]")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"wrote {path} ({len(content)} chars)"
    raise ValueError(f"unhandled tool: {kind}")


def extract_json(text):
    """Pull the first JSON object out of model output (fences tolerated)."""
    text = re.sub(r"```(?:json)?\s*", "", text)
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def call_model(prompt, model):
    """One short no-thinking generation. Returns (text, wall_s, eval_tok)."""
    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "options": {"temperature": 0, "num_ctx": 2048, "num_predict": 220},
    }).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL, data=body, headers={"Content-Type": "application/json"})
    t0 = time.time()
    with _OPENER.open(req, timeout=CALL_TIMEOUT_S) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("response", ""), time.time() - t0, data.get("eval_count")


def build_prompt(task, turns):
    """System + task + transcript, trimmed to stay inside the context."""
    transcript = ""
    for t in turns:
        transcript += f"\nAction: {t['action_json']}\nObservation: {t['observation']}\n"
    prompt = f"{SYSTEM}\n\nTASK: {task}\n{transcript}\nNext action (one JSON object only):"
    if len(prompt) > MAX_PROMPT_CHARS and len(turns) > 2:
        # Keep the task and the two most recent turns; drop older middle.
        return build_prompt(task, turns[-2:])
    return prompt


# Dry-run stub: canned actions that complete the task, so the loop's
# mechanics (check, tools, trace, report) can be exercised without Ollama.
def stub_actions(fixture_dir, out_dir):
    return [
        {"action": "read_file", "path": os.path.join(fixture_dir, "page1.html")},
        {"action": "read_file", "path": os.path.join(fixture_dir, "page2.html")},
        {"action": "write_file", "path": os.path.join(out_dir, "report.md"),
         "content": ("# Fixture report (dry run)\n\n"
                     "Verification code: PLATYPUS-4721\n"
                     "Arrival text: Arrival confirmed: you are on page two.\n")},
        {"action": "finish", "summary": "Report written with code and arrival text."},
    ]


def main():
    ap = argparse.ArgumentParser(description="local-agent starter loop")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--steps", type=int, default=8)
    ap.add_argument("--out-dir", default=os.path.join(HERE, "runs", "latest"))
    ap.add_argument("--dry-run", action="store_true",
                    help="stub model; exercises the loop without Ollama")
    ap.add_argument("--rollback", action="store_true",
                    help="roll back every recorded action in --out-dir's "
                    "ledger (reverse order) and exit; no model call")
    args = ap.parse_args()
    if args.steps < 1:
        print("usage error: --steps must be >= 1", file=sys.stderr)
        return 3

    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    ledger = Ledger(os.path.join(out_dir, "ledger.jsonl"))
    if args.rollback:
        try:
            undone = ledger.rollback()
        except RollbackError as e:
            print(f"ROLLBACK FAILED: {e}", file=sys.stderr)
            return 2
        print(f"ROLLED BACK {len(undone)} action(s) from {ledger.path}")
        for rec in undone:
            print(f"  undid seq {rec['undid_seq']}: {rec['target']}")
        return 0
    trace_path = os.path.join(out_dir, "trace.jsonl")
    report_path = os.path.join(out_dir, "report.md")
    task = (
        f"Read {os.path.join(FIXTURE_DIR, 'page1.html')} and find the "
        "verification code in the element with id 'target'. Then read "
        f"{os.path.join(FIXTURE_DIR, 'page2.html')} and find the arrival "
        "text in the element with id 'arrival'. Then write a report to "
        f"{report_path} containing BOTH the verification code and the "
        "arrival text, and finish."
    )

    trace = open(trace_path, "w", encoding="utf-8")

    def log(record):
        record["t"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        trace.write(json.dumps(record) + "\n")
        trace.flush()

    log({"event": "start", "model": None if args.dry_run else args.model,
         "mode": "dry-run" if args.dry_run else "live",
         "max_steps": args.steps, "task": task,
         "mem_available_mb": mem_available_mb()})

    turns = []
    stub = stub_actions(FIXTURE_DIR, out_dir) if args.dry_run else None
    finished = False

    for step in range(1, args.steps + 1):
        if args.dry_run:
            raw = json.dumps(stub[min(step - 1, len(stub) - 1)])
            wall, eval_tok = 0.0, None
        else:
            prompt = build_prompt(task, turns)
            raw, wall, eval_tok = None, None, None
            last_err = None
            for attempt in (1, 2):
                try:
                    raw, wall, eval_tok = call_model(prompt, args.model)
                    last_err = None
                    break
                except Exception as e:  # runner SIGKILL, timeout, conn drop
                    last_err = f"{type(e).__name__}: {e}"
                    log({"event": "generation_failed", "step": step,
                         "attempt": attempt, "error": last_err,
                         "mem_available_mb": mem_available_mb()})
                    time.sleep(10)
            if last_err is not None:
                log({"event": "aborted", "step": step, "reason":
                     "model call failed twice; runner may have been killed "
                     "(see the author's unpublished trial notes: "
                     "7 SIGKILLs, cause undetermined)"})
                print(f"step {step}: model call failed twice ({last_err}); "
                      "trace kept at " + trace_path)
                trace.close()
                return 2

        action = extract_json(raw)
        log({"event": "proposal", "step": step, "raw": raw[:1000],
             "wall_s": wall, "eval_tokens": eval_tok,
             "mem_available_mb": mem_available_mb()})
        if action is None:
            obs = ("Your last output was not a JSON action object. Output "
                   "exactly one JSON object and no other text.")
            turns.append({"action_json": raw[:500], "observation": obs})
            log({"event": "parse_failed", "step": step, "observation": obs})
            continue

        verdict, reason = check_action(action, out_dir)
        log({"event": "check", "step": step, "action": action,
             "verdict": verdict, "reason": reason})
        if verdict != "ALLOW":
            obs = f"Action DENIED: {reason}. Choose a different action."
            turns.append({"action_json": json.dumps(action), "observation": obs})
            continue
        if action["action"] == "finish":
            # FINISH CHECK (completion repair 2026-11-19): a finish action
            # is a CLAIM, not evidence. The deterministic completion check
            # runs here, inside the loop, before the task can end. A finish
            # with an unmet criterion is rejected and the unmet criterion
            # is fed back as the observation; the loop continues, bounded
            # by --steps. The model's own "done" never ends the run alone.
            ok, missing, detail = check_report(report_path)
            if ok:
                log({"event": "finished", "step": step,
                     "summary": action.get("summary", ""),
                     "completion_check": "PASS",
                     "code": detail["code"], "arrival": detail["arrival"]})
                finished = True
                break
            unmet = ", ".join(missing)
            obs = (f"Finish REJECTED: the completion check failed — "
                   f"missing: {unmet}. Fix the report, then finish again.")
            turns.append({"action_json": json.dumps(action),
                          "observation": obs})
            log({"event": "finish_rejected", "step": step,
                 "missing": missing, "observation": obs})
            print(f"step {step}: finish REJECTED — missing: {unmet}")
            continue
        try:
            obs = run_tool(action, out_dir, ledger)
        except Exception as e:
            obs = f"Tool error: {type(e).__name__}: {e}"
        turns.append({"action_json": json.dumps(action), "observation": obs})
        log({"event": "observation", "step": step, "observation": obs[:2000]})
        print(f"step {step}: {action['action']} -> {obs.splitlines()[0][:100]}")

    trace.close()
    if finished:
        print(f"FINISHED. Report verified: {report_path} "
              "(code + arrival text present, per the finish check).")
        return 0
    print(f"max steps ({args.steps}) reached without finishing; "
          f"trace at {trace_path}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
