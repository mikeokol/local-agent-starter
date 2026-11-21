# Local Agent Starter

A small tool-using agent loop that runs locally on an Ollama model — Python
3 standard library only, no new framework, no new dependency.

Built 2026-11-17 by Alfred, an AI operator working with Mike Umesumbu, to
answer: "if I wanted to build an agent and run it locally, how would I
begin?" Live page:
[Local Agent Starter](https://muse.ai/s/local-agent-starter-lk6xwmxsxnxwixp5/1w6GGsskAR5EEYtKAjuMrShuc1MoWzl-YTw8PlgjAxg).

## What it is

One loop, one step at a time:

1. **Propose** — the local model outputs exactly one JSON action:
   `read_file`, `list_dir`, `write_file`, or `finish`.
2. **Check** — a deterministic allowlist + path-confinement check judges
   the proposal before anything runs. Reads stay inside the fixture and
   starter dirs; writes stay inside the run dir. Anything else is DENIED
   and the denial is fed back to the model as its observation.
3. **Act** — the tool runs; its output becomes the next observation.
4. **Repeat** until the model calls `finish` or the step budget passes.

Two things make this starter different from a bare loop:

- **The finish check runs inside the loop.** A `finish` action is a
  claim, not evidence: `verify.py`'s completion check runs before the
  task can end. A finish with an unmet criterion is rejected, the unmet
  criterion is fed back as the observation, and the loop continues. The
  model's own "done" never ends the run alone.
- **Every write is ledgered and reversible.** `ledger.py` is an
  append-only JSONL ledger: each write records its before-state and its
  inverse. `python3 agent.py --rollback --out-dir <run>` undoes a run's
  recorded actions from the ledger alone, and refuses loudly if a target
  changed after the action.

Every step is appended to `runs/latest/trace.jsonl` the moment it
completes, so a killed run still leaves its evidence. The trace format
is the one
[The Done Test](https://muse.ai/s/the-done-test-un6xwnxgorxvxxi/00Iq2XHbD7WgcVjGQDomnlMg0aSpvy3XDh8wkRvW1UU)
grades.

## Run it

Mechanics-only test, no model needed:

```bash
python3 agent.py --dry-run
python3 verify.py
```

Live run (needs Ollama running with qwen3:8b pulled): bash run.sh --model qwen3:8b. The default tag qwen3:8b-ctx2k is the author's local variant.

See GUIDE.md for the full guide: why the loop is shaped this way (each
choice has trial evidence behind it), honest limits, and how to extend it.

## Honest limits

- **The fixture is in this repo** (`fixture/page1.html`,
  `fixture/page2.html` — the two pages from the original trial). To run
  the loop against different pages, replace them or point `FIXTURE_DIR`
  at another folder in `agent.py` and `verify.py`.
- run.sh expects Ollama to be running already; it does not start it.
- **The published `agent.py` omits a local experiment hook** present in
  the author's working copy (a log-only shadow consultation added
  2026-11-20 for a bounded experiment). The published loop is otherwise
  the working loop, including the in-loop finish check and the ledger.
- The model may waste steps on malformed JSON; the loop feeds parse
  failures back and retries, but a live run can still burn its step
  budget without finishing. The trace shows exactly what happened; the
  verifier is the judge.

## Files

- `agent.py` — the loop (stdlib only).
- `verify.py` — ground-truth judge + the finish check.
- `ledger.py` — append-only per-action ledger with rollback.
- `fixture/` — the two-page HTML fixture the default task reads.
- `run.sh` — one-command entry (waits for Ollama, runs agent, verifies).
- `GUIDE.md` — the full guide.
- `RECEIPT.md` — what was reused to build the starter, and the
  build-time smoke check.
- `LICENSE` — MIT.

## Origin

Built 2026-11-17 after a local-model trial (Qwen 8B on a 7.7 GB box)
showed the binding constraints were harness- and box-side, not
model-side. Contact: 125mikeokol@gmail.com,
[linkedin.com/in/mike-umesumbu-916324168](https://linkedin.com/in/mike-umesumbu-916324168).
