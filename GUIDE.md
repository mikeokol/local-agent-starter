# LOCAL-AGENT STARTER — GUIDE

**Built 2026-11-17. Answers Mike's question (just after midnight today):
"if I wanted to build an agent and run it locally, how would I begin to
do so?"** The answer is this starter: a small agent loop that runs one
real task end-to-end on this box, assembled from pieces that already
exist here. No new framework, no new dependency, $0.

## Run it

```bash
bash run.sh
```

That waits for a running Ollama to list the model, runs the agent,
then runs the verifier. Expected wall for a live
run: ~2 min cold model load + 3–5 steps at ~25–75 s each ≈ **5–10 min**.
Exit 0 + `VERDICT: PASS` means the task completed and the report holds
both required facts.

Mechanics-only test, no model needed:

```bash
python3 agent.py --dry-run
python3 verify.py
```

## What the agent does

The task is the same goal the browser-use agent failed on Nov 16 (Qwen
trial, Leg 3): read page 1 of the fixture, extract the verification
code; read page 2, extract the arrival text; write a report containing
both. The difference is the loop, not the goal.

The loop, one step at a time:

1. **Propose** — the local model (qwen3:8b-ctx2k, Ollama) outputs exactly
   one JSON action: `read_file`, `list_dir`, `write_file`, or `finish`.
2. **Check** — a deterministic allowlist + path-confinement check judges
   the proposal before anything runs (pattern from Alfred's execution
   adapter; see RECEIPT.md). Reads stay inside the fixture/starter dirs;
   writes stay inside the run dir. Anything else is DENIED and the
   denial is fed back to the model as its observation.
3. **Act** — the tool runs; its output becomes the next observation.
4. **Repeat** until the model calls `finish` or 8 steps pass.

Every step is appended to `runs/latest/trace.jsonl` the moment it
completes, so a killed run still leaves its evidence. `verify.py` then
judges the report against ground truth read fresh from the fixture.

## Why it is shaped this way (each choice has trial evidence)

- **No thinking, short generations.** qwen3:8b thinks by default; a
  1000+ token thinking trace at ~2 tok/s takes 10–20 min per step and
  blew browser-use's 300 s deadline three times (Leg 3: zero steps
  completed). Every call here sets `"think": false` and caps output at
  220 tokens — one short JSON action per step, ~25–75 s.
- **ctx2k model.** `qwen3:8b-ctx2k` halves the KV cache vs the 4096
  default, restoring load headroom on the 7.7 GB box. `num_ctx 2048`
  is also passed per-request, so the loop survives even if the tag is
  ever missing.
- **Retry once, then stop with a record.** The Ollama runner was
  SIGKILLed 7 times in the trial with 6.1–6.3 GiB free — not host OOM,
  cause undetermined. A failed generation retries once after 10 s; if
  it fails again the run stops, exit 2, trace intact.
- **No proxies on loopback.** The box's bracketed-IPv6 `no_proxy`
  breaks httpx URL parsing (Leg 1 false start). The loop uses urllib
  with proxies disabled outright.
- **No browser.** The browser leg is deliberately absent: browser-use +
  a thinking 8B on this box completed zero steps. The fixture is local
  HTML, so plain file reads do the same job. A browser would add a
  whole failure surface for nothing this task needs.

## Honest limits — what runs locally and what doesn't

**Runs on this box:** a short-generation tool loop on qwen3:8b-ctx2k
with a 2–4 step task, as built here. The trial's Leg 2 showed the same
model making 16/16 correct-in-substance decisions on short prompts.

**Does NOT run on this box:** a browser-driving agent on an 8B thinking
model (Leg 3: 0 steps, 3× 300 s timeouts); long generations (each
1000-token thinking trace is ~10 min and widens the SIGKILL window);
anything needing more than ~2 tok/s sustained. The trial's bottom line
stands: the binding constraints are harness- and box-side, not
model-side — a better model does not help until these are addressed.

**Known weaknesses of this starter, stated plainly:**
- The model may waste steps on malformed JSON. The loop feeds parse
  failures back as observations and retries, but a live run can still
  burn its 8 steps without finishing. The trace shows exactly what
  happened; the verifier is the judge.
- The runner SIGKILL hazard is undiminished — it struck with 6 GiB
  free. Short generations shrink the window; they do not close it.
- Leg 2's format findings apply: this model produces correct judgments
  in sometimes-unusable output (0/16 scorable under the trial's frozen
  scorer). The JSON-extraction step is the mitigation, not a cure.
- The task is small on purpose. It proves the loop, not that an 8B
  local agent can do real work — the trial closed that larger question
  with evidence, and this starter does not reopen it.

**What cloud Muse has that this starter does not:** frontier reasoning,
memory across conversations, connectors, a browser, scheduled wakes,
voice, subagents. This is a bare loop with a local brain. Everything
else is a build — which is the point of a starter.

## Extend it

- **Add a tool:** add its name to the allowlist in `check_action()`,
  implement it in `run_tool()`, and name it in the `SYSTEM` prompt.
  Keep the confinement rule: every new tool gets an explicit boundary
  in the check, or it does not exist.
- **Change the task:** edit the `task` string in `main()` and the
  ground truth in `verify.py`. Keep tasks to 2–5 short steps.
- **Another model:** `--model <tag>`, with the tag present in the
  trial's Ollama models dir. Smaller/faster models (e.g. a 3B) would
  cut per-step latency; none is installed here — pulling one is a
  new download, not part of this starter.
- **On the iMac:** this starter is the answer for *this box*. The
  iMac build is a separate branch, gated on the About This Mac
  reading — see author's local file, not in this repo.
  Do not treat this starter as an iMac install guide.

## Files

- `agent.py` — the loop (stdlib only).
- `verify.py` — ground-truth judge.
- `run.sh` — one-command entry (waits for Ollama, runs agent, verifies).
- `GUIDE.md` — this file.
- `RECEIPT.md` — what was reused, limits, and the 14:13 verification
  instructions.
- `runs/` — run outputs; `runs/latest/` is the current run.
