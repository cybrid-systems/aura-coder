"""Host side of the Aura control plane: a long-lived `aura aura/server.aura` process spoken to over pipes.

Every policy decision (DECIDE) and every policy mutation (REPORT -> mutate:rebind, VERDICT -> ast:restore)
happens inside that Aura process; this module only frames requests and times round trips.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRACE = os.environ.get("AURA_CODER_TRACE")    # append every request line to this file (debug / repro)


def aura_env() -> tuple[str, dict]:
    aura = os.environ.get("AURA_BIN") or "aura"
    env = os.environ.copy()
    lib = os.environ.get("AURA_LIB")
    if lib:
        env["AURA_PATH"] = lib + (":" + env["AURA_PATH"] if env.get("AURA_PATH") else "")
    # Soft (set-code / mutate:rebind in a local program) still needs the sandbox off: cybrid-systems/aura#4575
    env.setdefault("AURA_SANDBOX", "off")
    env.setdefault("AURA_PIPELINE_STRICT", "0")
    return aura, env


def _clean(s: str) -> str:
    return s.replace("\t", " ").replace("\n", " ") or "-"


class AuraControl:
    def __init__(self, learn: bool = True, min_evidence: int = 2):
        aura, env = aura_env()
        env["AURA_CODER_POLICY"] = str(ROOT / "aura" / "policy_seed.aura")
        env["AURA_CODER_MIN_EVIDENCE"] = str(min_evidence)
        t0 = time.perf_counter()
        self.p = subprocess.Popen([aura, str(ROOT / "aura" / "server.aura")], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1,
                                  env=env, cwd=str(ROOT))
        ready = self._read()
        self.startup_s = time.perf_counter() - t0
        if not ready.get("ready"):
            raise RuntimeError(f"aura control plane failed to start: {ready}")
        self.lat = {}           # op -> [seconds]
        if not learn:
            self.call("LEARN", "0")

    def _read(self) -> dict:
        while True:
            line = self.p.stdout.readline()
            if not line:
                err = self.p.stderr.read()[-2000:] if self.p.stderr else ""
                raise RuntimeError(f"aura control plane exited (rc={self.p.poll()}): {err}")
            if line.startswith("R "):
                return json.loads(line[2:])

    def call(self, cmd: str, *fields: str, tag: str | None = None) -> dict:
        t0 = time.perf_counter()
        if TRACE:
            with open(TRACE, "a") as fh:
                fh.write("\t".join([cmd, *[_clean(str(f)) for f in fields]]) + "\n")
        self.p.stdin.write("\t".join([cmd, *[_clean(str(f)) for f in fields]]) + "\n")
        self.p.stdin.flush()
        r = self._read()
        self.lat.setdefault(tag or cmd, []).append(time.perf_counter() - t0)
        if "error" in r:
            raise RuntimeError(f"aura control plane: {r['error']}")
        return r

    @staticmethod
    def _key(f: dict) -> list[str]:
        return [f["etype"], f["msgpat"], f["delta"], f["node"]]

    def decide(self, f: dict, tag: str = "DECIDE") -> dict:
        return self.call("DECIDE", *self._key(f), tag=tag)

    def report(self, f: dict, solved: bool, winop: str) -> dict:
        r = self.call("REPORT", *self._key(f), "1" if solved else "0", winop or "", tag="REPORT")
        if r.get("propose"):
            self.lat.setdefault("MUTATE", []).append(self.lat["REPORT"][-1])
        return r

    def verdict(self, keep: bool) -> dict:
        return self.call("VERDICT", "keep" if keep else "drop", tag="KEEP" if keep else "ROLLBACK")

    def source(self) -> str:
        return self.call("SOURCE")["source"]

    def reset(self) -> dict:
        return self.call("RESET")

    def close(self):
        try:
            self.p.stdin.write("QUIT\n")
            self.p.stdin.flush()
            self.p.wait(timeout=10)
        except Exception:
            self.p.kill()
