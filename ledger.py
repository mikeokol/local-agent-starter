#!/usr/bin/env python3
"""ledger.py — minimal per-action ledger with rollback (2026-11-19).

Origination test 11:35, queue item 26: Agent action ledger with rollback.
Customer need: after an agent incident, the responder needs to know exactly
what the agent touched and undo exactly that. 75% of orgs had an
AI-contributing production incident in the past year (Futurum's own survey,
839 IT decision makers, fielded July 2026); 88% cannot roll back agent
actions without disruption (Rubrik Zero Labs, released 2026-04-16).

Design (stdlib only, no model/Ollama, no network):
- Append-only JSONL ledger. Each entry records: seq, timestamp, action,
  target path, before-state (prior file bytes, base64, or null if absent,
  plus sha256), after-state (new bytes + sha256), and the inverse
  operation needed to undo it.
- Inverse operations supported: "restore" (write back prior bytes),
  "delete" (remove a file that did not exist before).
- rollback() reloads entries from disk (never trusts in-memory state),
  walks them in reverse order, applies each inverse, and appends a
  "rollback" record per undone entry. Original entries are never edited.
- A rollback that cannot restore its target (target externally deleted /
  moved, or before-bytes mismatch on a pre-check) raises RollbackError
  and stops loudly — it never claims success it did not achieve.

Usage is demonstrated by the sandbox experiment in
author's local file, not in this repo.
Integrated into agent.py's tool loop 2026-11-19 (queue item 27): write_file
actions route through record_write, and `python3 agent.py --rollback
--out-dir <run>` undoes a run's recorded actions from its ledger.
"""

import base64
import hashlib
import json
import os
import time


class RollbackError(Exception):
    """Raised when a rollback cannot be completed exactly as recorded."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _b64(data):
    return None if data is None else base64.b64encode(data).decode("ascii")


def _unb64(s):
    return None if s is None else base64.b64decode(s.encode("ascii"))


class Ledger:
    def __init__(self, ledger_path):
        self.path = os.path.abspath(ledger_path)
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        if not os.path.exists(self.path):
            open(self.path, "w", encoding="utf-8").close()

    def entries(self):
        out = []
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out

    def _append(self, entry):
        entry["seq"] = len(self.entries()) + 1
        entry["t"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")
        return entry

    def record_write(self, target, new_content: bytes, note=""):
        """Record + perform a file write. Returns the ledger entry."""
        target = os.path.abspath(target)
        before = None
        if os.path.exists(target):
            with open(target, "rb") as f:
                before = f.read()
        # Perform the write first, then record (so the ledger never
        # claims an action that did not happen).
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        with open(target, "wb") as f:
            f.write(new_content)
        inverse = "delete" if before is None else "restore"
        return self._append({
            "kind": "action",
            "action": "write_file",
            "target": target,
            "note": note,
            "before_bytes_b64": _b64(before),
            "before_sha256": _sha256(before) if before is not None else None,
            "after_bytes_b64": _b64(new_content),
            "after_sha256": _sha256(new_content),
            "inverse": inverse,
        })

    def record_state_change(self, state_path, key, new_value, note=""):
        """Record + perform a JSON state-file key change.

        The whole state file is the unit of record: before/after are the
        full file bytes, so rollback restores the exact prior file.
        """
        state_path = os.path.abspath(state_path)
        before = None
        if os.path.exists(state_path):
            with open(state_path, "rb") as f:
                before = f.read()
            state = json.loads(before.decode("utf-8"))
        else:
            state = {}
        state[key] = new_value
        new_bytes = (json.dumps(state, sort_keys=True, indent=2) + "\n").encode("utf-8")
        return self.record_write(state_path, new_bytes, note=note or f"state {key}={new_value!r}")

    def rollback(self):
        """Undo all action entries, reverse order, from disk only.

        Returns the list of rollback records appended. Raises RollbackError
        on the first entry that cannot be restored exactly; entries
        already undone before the failure stay undone and are recorded.
        """
        entries = [e for e in self.entries() if e.get("kind") == "action"]
        undone = []
        for entry in reversed(entries):
            target = entry["target"]
            inverse = entry["inverse"]
            try:
                if inverse == "restore":
                    before = _unb64(entry["before_bytes_b64"])
                    assert before is not None, "restore needs before bytes"
                    # Loud failure if the current file is not what the
                    # ledger says the action left behind: something else
                    # touched it after the action, so blind restore would
                    # hide that interference.
                    if os.path.exists(target):
                        with open(target, "rb") as f:
                            current = f.read()
                        if _sha256(current) != entry["after_sha256"]:
                            raise RollbackError(
                                f"target {target} changed after action "
                                f"(current sha256 {_sha256(current)[:16]} != "
                                f"ledger after sha256 {entry['after_sha256'][:16]}); "
                                "refusing blind restore")
                    else:
                        raise RollbackError(
                            f"target {target} missing at rollback; "
                            "cannot restore before-state to a moved/deleted path")
                    with open(target, "wb") as f:
                        f.write(before)
                elif inverse == "delete":
                    if os.path.exists(target):
                        with open(target, "rb") as f:
                            current = f.read()
                        if _sha256(current) != entry["after_sha256"]:
                            raise RollbackError(
                                f"target {target} changed after action; "
                                "refusing delete-rollback")
                        os.remove(target)
                    else:
                        raise RollbackError(
                            f"target {target} already gone at rollback; "
                            "cannot verify delete-rollback")
                else:
                    raise RollbackError(f"unknown inverse {inverse!r} for {target}")
            except RollbackError:
                raise
            except Exception as e:
                raise RollbackError(f"rollback of seq {entry['seq']} ({target}): {type(e).__name__}: {e}")
            rec = self._append({
                "kind": "rollback",
                "action": "rollback",
                "target": target,
                "note": f"undid seq {entry['seq']} ({entry['action']})",
                "before_bytes_b64": None,
                "before_sha256": None,
                "after_bytes_b64": None,
                "after_sha256": None,
                "inverse": "none",
                "undid_seq": entry["seq"],
            })
            undone.append(rec)
        return undone
