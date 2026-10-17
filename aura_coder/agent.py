"""The coding agent: data plane (tests, patches) in Python, repair policy in the Aura workspace.

One task:  run tests -> features -> Aura DECIDE (class, budget, operator order) -> try candidates in that
order until tests pass or the budget is spent.  After the task (adaptive modes): post-mortem search when it
failed, REPORT the outcome to the Aura learner; if the learner mutated the policy, gate it by replaying the
recent window under old vs new decisions, then VERDICT keep (commit) or drop (ast:restore rollback).
"""
from __future__ import annotations

import hashlib
import json
import random
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

from .control import AuraControl, ROOT
from .corpus import Task
from .operators import OPERATORS, candidates
from .runner import features, run_tests

sys.path.insert(0, str(ROOT / "third_party" / "aura-loop"))
try:
    from aura_loop.memory import Memory      # reused: SQLite KEEP/ROLLBACK/REJECT transition table
except ImportError:                          # submodule not checked out
    Memory = None

PM_BUDGET = 40          # post-mortem search budget (adaptive only; counted as overhead)
GATE_WINDOW = 10        # replay the last N tasks


@dataclass
class Episode:
    tid: str
    bug: str
    phase: str
    solved: bool
    attempts: int
    cls: str
    winop: str = ""
    pm_attempts: int = 0
    gate_attempts: int = 0
    version: int = 0
    mutation: dict | None = None


def attempt(task: Task, feats: dict, decision: dict) -> tuple[bool, int, str]:
    """Try candidates in policy order within budget. Returns (solved, attempts, winning operator)."""
    n, budget = 0, int(decision["budget"])
    for op in decision["order"]:
        for cand in candidates(task.source, feats, op):
            if n >= budget:
                return False, n, ""
            n += 1
            if run_tests(cand, task.tests).ok:
                return True, n, op
    return False, n, ""


def post_mortem(task: Task, feats: dict, skip: int) -> tuple[str, int]:
    """Wider search after a failed task, to give the learner evidence. Counted as overhead attempts."""
    n = 0
    for op in OPERATORS:
        for cand in candidates(task.source, feats, op):
            if n >= PM_BUDGET:
                return "", n
            n += 1
            if run_tests(cand, task.tests).ok:
                return op, n
    return "", n


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:12]


class Agent:
    """mode: static | restart | adaptive | adaptive-nogate"""

    def __init__(self, mode: str, outdir: Path | None = None, noise: float = 0.0, seed: int = 0):
        self.mode = mode
        self.noise = noise                      # P(reported winning operator is wrong): mis-attributed fixes
        self.rng = random.Random(1000 + seed)
        self.ctl = None if mode == "restart" else AuraControl(learn=mode.startswith("adaptive"))
        self.history: list[tuple[Task, dict]] = []
        self.episodes: list[Episode] = []
        self.restart_s: list[float] = []
        self.lat: dict[str, list[float]] = {}
        self.outdir = outdir
        self.prov = []
        self.mem = None
        if outdir:
            outdir.mkdir(parents=True, exist_ok=True)
            if Memory:
                db = outdir / "provenance.sqlite"
                db.unlink(missing_ok=True)
                self.mem = Memory(str(db))
        self.src = self.ctl.source() if self.ctl else ""
        self._log_version(0, {"kind": "seed"}, "SEED", None)

    # ------------------------------------------------------------------ provenance
    def _log_version(self, version: int, prop: dict, verdict: str, gate: dict | None, before: str = ""):
        rec = {"version": version, "verdict": verdict, "proposal": prop, "gate": gate,
               "source_sha": _sha(self.src), "source": self.src, "t": time.time()}
        self.prov.append(rec)
        if self.mem and verdict in ("KEEP", "ROLLBACK"):
            self.mem.writeback(repo="aura-coder", symbol=prop.get("kind", ""), before_src=before,
                               after_src=self.src, intent=json.dumps(prop), verdict=verdict,
                               reason=json.dumps(gate), sha=_sha(self.src))

    # ------------------------------------------------------------------ one task
    def run_task(self, task: Task) -> Episode:
        ctl = self.ctl
        if self.mode == "restart":     # a fresh agent session per task: cold Aura, seed policy, no memory
            t0 = time.perf_counter()
            ctl = AuraControl(learn=True)
            self.restart_s.append(time.perf_counter() - t0)
        r0 = run_tests(task.source, task.tests)
        feats = features(task.source, r0)
        decision = ctl.decide(feats)
        solved, n, winop = attempt(task, feats, decision)
        ep = Episode(task.tid, task.bug, task.phase, solved, n, decision["cls"], winop,
                     version=decision.get("version", 0))
        if self.mode.startswith("adaptive"):
            if not solved:
                winop, ep.pm_attempts = post_mortem(task, feats, n)
            self.history.append((task, feats))
            window = self.gate_window(feats)
            old = [ctl.decide(f, tag="GATE_DECIDE") for _, f in window]
            if winop and self.noise and self.rng.random() < self.noise:
                winop = self.rng.choice([o for o in OPERATORS if o != winop])
            rep = ctl.report(feats, solved, winop)
            prop = rep.get("propose")
            if prop:
                ep.mutation = prop
                before = self.src
                self.src = ctl.source()
                new = [ctl.decide(f, tag="GATE_DECIDE") for _, f in window]
                if not (prop.get("rebind_ok") and prop.get("eval_ok")):
                    keep, gate = False, {"reason": "mutate:rebind/eval-current failed"}
                elif self.mode == "adaptive-nogate":
                    keep, gate = True, {"reason": "no gate"}
                else:
                    keep, gate, ga = self.gate(window, old, new)
                    ep.gate_attempts = ga
                v = ctl.verdict(keep)
                if not keep:
                    self.src = ctl.source()
                    assert self.src == before, "ast:restore did not restore the workspace source"
                self._log_version(v["version"], prop, "KEEP" if keep else "ROLLBACK", gate, before)
        if self.mode == "restart":
            for k, v in ctl.lat.items():
                self.lat.setdefault(k, []).extend(v)
            ctl.close()
        self.episodes.append(ep)
        return ep

    def gate_window(self, feats):
        """Replay set: the last GATE_WINDOW tasks plus earlier tasks with the same failure signature (cap 2x)."""
        key = lambda f: (f["etype"], f["msgpat"], f["delta"], f["node"])
        recent = self.history[-GATE_WINDOW:]
        same = [h for h in self.history[:-GATE_WINDOW] if key(h[1]) == key(feats)][-GATE_WINDOW:]
        return same + recent

    def gate(self, window, old, new):
        """Replay the recent window: KEEP iff no fewer solves and (more solves or fewer attempts)."""
        so = sn = ao = an = 0
        runs = 0
        for (task, feats), do, dn in zip(window, old, new):
            if (do["order"], do["budget"]) == (dn["order"], dn["budget"]):
                continue                  # identical decision -> identical replay; skip the data plane
            s1, n1, _ = attempt(task, feats, do)
            s2, n2, _ = attempt(task, feats, dn)
            so += s1; sn += s2; ao += n1; an += n2; runs += n1 + n2
        keep = sn >= so and (sn > so or an < ao)
        return keep, {"old_solved": so, "new_solved": sn, "old_attempts": ao, "new_attempts": an}, runs

    def close(self):
        if self.ctl:
            for k, v in self.ctl.lat.items():
                self.lat.setdefault(k, []).extend(v)
            self.ctl.close()
        if self.outdir:
            with open(self.outdir / "provenance.jsonl", "w") as fh:
                for rec in self.prov:
                    fh.write(json.dumps(rec) + "\n")
            with open(self.outdir / "episodes.jsonl", "w") as fh:
                for ep in self.episodes:
                    fh.write(json.dumps(asdict(ep)) + "\n")
