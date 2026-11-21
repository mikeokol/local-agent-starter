# LOCAL-AGENT STARTER — RECEIPT (built 2026-11-17, ~13:5x ET)

This is the build receipt as written on 2026-11-17, before the first live run and before the fixture was copied into this repo (2026-11-21). Local paths have been removed. The live run happened the same day, 19:14-19:18 UTC: four steps, finished. Its trace is controls/positive-trace.jsonl in The Done Test.

## What was reused (no-rebuild check — all verified on disk before building)

| Piece | Path | How it is used |
|---|---|---|
| Ollama server binary 0.40.16 | author's local file, not in this repo | Started by the trial's restart script; the starter calls it, never copies it |
| Ollama restart script | author's local file, not in this repo | `run.sh` calls it verbatim to start the server + resume the pull if needed |
| Model qwen3:8b (5.2 GB) + ctx2k tag | author's local file, not in this repo (manifests-v2: `ollama.com/library/qwen3/8b-ctx2k`, verified present) | Default model `qwen3:8b-ctx2k`; `num_ctx 2048` also passed per-request |
| ctx2k Modelfile | author's local file, not in this repo | Design reference for the per-request `num_ctx` fallback |
| Leg 3 fixture (page1/page2) | author's local file, not in this repo | The task's target, read in place — not copied |
| Leg 3 task + verdict shape | author's local file, not in this repo | Same goal (code + arrival text); same PASS shape (`PLATYPUS-4721` + page-two text present), with ground truth read fresh from the fixture instead of hardcoded |
| Trial evidence + limits | author's local file, not in this repo | Every design choice cites it (no-think, short generations, ctx2k, retry-once, no-proxy opener, no browser) |
| Execution-adapter pattern | author's local file, not in this repo | `check_action()` mirrors its shape (proposal → deterministic check → logged verdict). The adapter itself is NOT called — it judges Alfred's mandate scopes, which are not this agent's |
| Platform map + operating manual | author's local file, not in this repo (Part 1), author's local file, not in this repo | No-rebuild check sources; confirmed Ollama/g4-venv/adapter inventory before building |
| iMac scope (context, not reused code) | author's local file, not in this repo | Guide points at it for the separate iMac branch |

NOT reused, deliberately: browser-use 1.0.2 + the g4 venv
(author's local file, not in this repo) —
that is the leg that completed zero steps in the trial (thinking latency
vs the 300 s deadline). The starter drops the browser rather than
re-running a failed leg. No new framework, no new package, no new model
download.

## What the starter does

A stdlib-only Python loop (`agent.py`, ~370 lines): local model proposes
one JSON action per step → deterministic allowlist/path-confinement
check → tool runs (read_file / list_dir / write_file / finish) →
observation feeds the next step. Task: extract the verification code
from the fixture's page 1 and the arrival text from page 2, write a
report containing both. `verify.py` judges the report against ground
truth read fresh from the fixture. `run.sh` is the one-command entry.

## Build-time smoke check (safe, no model load)

Ran 2026-11-17 ~13:5x ET: `agent.py --dry-run` (stub model) → 4 steps,
all checks ALLOW, report written, `verify.py` → **PASS** (both facts
found). Check-function unit probes: write outside run dir DENIED, read
outside fixture/starter dirs DENIED, unknown action class DENIED,
in-confinement read ALLOW, fenced-JSON extraction works, non-JSON
returns None. The smoke run caught one real bug: the first verifier
required the full target-element sentence ("The verification code is
PLATYPUS-4721.") in the report; fixed to extract the code token
(`PLATYPUS-4721`) — the code is the fact, the sentence is packaging.
Artifacts preserved at `runs/dry-run-2026-11-17/`.

**NOT done at build time (by design): no live model run.** Ollama was
down and only 643 MB was available at build time, so loading the 5.2 GB
model was not attempted. The live run is the 14:13 work wake's job.

## Known limits

- Per-step latency ~25–75 s at ~2 tok/s; a live run is ~5–10 min wall.
- Runner SIGKILL hazard undiminished (7 in the trial, cause
  undetermined, struck with 6 GiB free). Short generations shrink the
  window; retry-once + JSONL trace are the mitigations.
- The model may waste steps on malformed JSON (parse-failure feedback
  loop is the mitigation; 8-step cap bounds the damage).
- No browser, no network tools, no sends, no credentials — by design.
- The task proves the loop, not that an 8B local agent can do real
  work; the trial's closed verdict on that larger question stands.

## What the 14:13 verification run should execute

```
cd local-agent-starter
free -m | head -2        # record available memory BEFORE the load
bash run.sh
```

Expected: Ollama starts (restart script), `qwen3` listed, agent runs
3–5 live steps and finishes, `verify.py` prints `VERDICT: PASS`,
exit 0. Total wall ~5–10 min plus model load.

Record in the wake receipt: memory available before load, model-load
wall time, per-step wall times + eval tokens (from
`runs/latest/trace.jsonl`), the verifier verdict, and the report's
contents. If the agent exits 2 (model call failed twice), record the
trace's `generation_failed` entries and do NOT re-run blindly — the
SIGKILL hazard is a finding, not a retry prompt; one re-run after a
few minutes is acceptable, a second is not. If it exits 1 (max steps,
no finish), record the trace's proposals — malformed-JSON waste is a
finding about the model's output discipline. Do not edit the starter
to rescue a failing run; the verification judges the starter as built.
