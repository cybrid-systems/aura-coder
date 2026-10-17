"""Data plane: run a task's tests in a sandboxed subprocess and turn the first failure into features.

Sandbox: fresh temp dir, `python3 -I -S`, empty env, rlimits (CPU 2 s, AS 512 MiB, FSIZE 1 MiB, NOFILE 64),
wall-clock timeout. No network isolation (container-level only); the corpus is generated, not user code.
"""
from __future__ import annotations

import ast
import json
import os
import re
import resource
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

HARNESS = r'''
import json, sys, traceback, importlib.util
spec = importlib.util.spec_from_file_location("prog", "prog.py")
out = {"ok": True, "passed": 0, "total": 0}
cases = json.loads(open("cases.json").read())
out["total"] = len(cases)
try:
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
except BaseException as e:
    tb = [f for f in traceback.extract_tb(e.__traceback__) if f.filename.endswith("prog.py")]
    print("RESULT " + json.dumps({"ok": False, "passed": 0, "total": len(cases), "etype": type(e).__name__,
          "msg": str(e)[:300], "line": tb[-1].lineno if tb else 0, "phase": "import"})); sys.exit(0)
for i, (args, want) in enumerate(cases):
    try:
        got = mod.fn(*args)
    except BaseException as e:
        tb = [f for f in traceback.extract_tb(e.__traceback__) if f.filename.endswith("prog.py")]
        out.update(ok=False, etype=type(e).__name__, msg=str(e)[:300], line=tb[-1].lineno if tb else 0, case=i)
        break
    if got != want or type(got) is bool and type(want) is not bool:
        try:
            json.dumps(got)
            g = got
        except TypeError:
            g = repr(got)
        out.update(ok=False, etype="AssertionError", msg="", got=g, want=want, line=0, case=i)
        break
    out["passed"] += 1
print("RESULT " + json.dumps(out))
'''


def _limits():
    resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
    resource.setrlimit(resource.RLIMIT_AS, (512 << 20, 512 << 20))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1 << 20, 1 << 20))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    os.setsid()


@dataclass
class TestResult:
    ok: bool
    passed: int
    total: int
    etype: str = ""
    msg: str = ""
    line: int = 0
    got: object = None
    want: object = None

    @classmethod
    def from_json(cls, d: dict) -> "TestResult":
        return cls(d.get("ok", False), d.get("passed", 0), d.get("total", 0), d.get("etype", ""),
                   d.get("msg", ""), d.get("line", 0), d.get("got"), d.get("want"))


RUNS = {"n": 0}


def run_tests(source: str, tests, timeout: float = 5.0) -> TestResult:
    RUNS["n"] += 1
    with tempfile.TemporaryDirectory(prefix="aura-coder-") as tmp:
        p = Path(tmp)
        (p / "prog.py").write_text(source)
        (p / "cases.json").write_text(json.dumps([[list(a), w] for a, w in tests]))
        (p / "harness.py").write_text(HARNESS)
        try:
            r = subprocess.run([sys.executable, "-I", "-S", "harness.py"], cwd=tmp, env={}, capture_output=True,
                               text=True, timeout=timeout, preexec_fn=_limits)
        except subprocess.TimeoutExpired:
            return TestResult(False, 0, len(tests), "Timeout", "test run timed out")
    for line in r.stdout.splitlines():
        if line.startswith("RESULT "):
            return TestResult.from_json(json.loads(line[7:]))
    return TestResult(False, 0, len(tests), "Crash", (r.stderr or r.stdout)[-200:])


# ---------------------------------------------------------------- features
KEEP_NAMES = {"NoneType", "str", "int", "float", "list", "dict", "tuple", "bool"}


def msg_pattern(msg: str) -> str:
    m = re.sub(r"'([^']*)'", lambda g: "'" + (g.group(1) if g.group(1) in KEEP_NAMES else "_") + "'", msg)
    m = re.sub(r"\d+", "N", m)
    return re.sub(r"[\t\n]", " ", m)[:80] or "-"


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def delta(got, want) -> str:
    if got is None and want is not None:
        return "none"
    if isinstance(got, bool) and isinstance(want, bool):
        return "bool-flip"
    if _num(got) and _num(want):
        d = got - want
        if abs(d) == 1:
            return "off-by-one"
        if want != 0 and got == -want:
            return "sign"
        return "numeric-other"
    if isinstance(got, (list, str)) and type(got) is type(want):
        dl = len(got) - len(want)
        return "len-off-by-one" if abs(dl) == 1 else "content" if dl == 0 else "len-other"
    return "type"


def stmt_kind(source: str, line: int) -> str:
    if not line:
        return "-"
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return "-"
    best = None
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt) and node.lineno <= line <= (node.end_lineno or node.lineno):
            if not isinstance(node, (ast.FunctionDef, ast.For, ast.If, ast.While)) or node.lineno == line:
                best = node
    return type(best).__name__ if best else "-"


def features(source: str, r: TestResult) -> dict:
    """Failure -> feature dict. The policy key is (etype, msgpat, delta, node)."""
    if r.etype == "AssertionError":
        return {"etype": "AssertionError", "msgpat": "-", "delta": delta(r.got, r.want), "node": "-",
                "line": 0, "msg": ""}
    return {"etype": r.etype or "-", "msgpat": msg_pattern(r.msg), "delta": "-", "node": stmt_kind(source, r.line),
            "line": r.line, "msg": r.msg}
