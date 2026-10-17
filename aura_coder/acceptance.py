"""Rebind-correctness acceptance checks for the Aura build in AURA_BIN.

Each acceptance/<name>/repro.aura is run from its own directory (lib/ on AURA_PATH); the last non-empty stdout
line must equal expect.txt. Issue repros are copied from cybrid-systems/aura (#4546 #4547 #4550 #4552 #4583 #4584);
coder-cycle is aura-coder's own rebind/rollback shape.
"""
from __future__ import annotations

import subprocess
import sys

from .control import ROOT, aura_env

CHECKS = {
    "4546": "top-level define dropped when its initializer runs set-code + eval-current (letrec)",
    "4547": "module caller runs a different workspace define after mutate:rebind",
    "4550": "third rebind leaves a caller as 'invalid closure'",
    "4552": "non-tail (error ...) in a workspace define is dropped",
    "4583": "10 rebinds next to a self-recursive define stay flat (no 4x-per-rebind blow-up)",
    "4584": "2nd call of a workspace define whose sibling uses filter runs the right define",
    "coder-cycle": "aura-coder: 3 rebinds + snapshot/rebind/restore round trip",
}


def run_check(name: str) -> tuple[bool, str]:
    d = ROOT / "acceptance" / name
    aura, env = aura_env()
    env["AURA_PATH"] = str(d / "lib") + ":" + env.get("AURA_PATH", "")
    try:
        p = subprocess.run([aura, "repro.aura"], cwd=str(d), env=env, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return False, "timeout"
    lines = [l for l in p.stdout.splitlines() if l.strip() and not l.startswith("⚠")]
    got = lines[-1].strip() if lines else f"(no output, rc={p.returncode}) {p.stderr[-200:]}"
    return got == (d / "expect.txt").read_text().strip(), got


def main() -> int:
    bad = 0
    for name, what in CHECKS.items():
        ok, got = run_check(name)
        bad += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name:12s} {what}\n      got: {got}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
