"""python3 -m aura_coder {bench,latency,acceptance,corpus}"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

from .control import ROOT, aura_env


def host_round_trips(n: int) -> None:
    """Host -> Aura server round trips: DECIDE, and specialize (snapshot + 3 rebinds + eval-current) / rollback."""
    import time
    from .control import AuraControl
    c = AuraControl(learn=True)
    f = {"etype": "AssertionError", "msgpat": "-", "delta": "off-by-one", "node": "-"}
    for _ in range(5 * n):
        c.decide(f)
    for i in range(min(n, 40)):
        g = {"etype": "KeyError", "msgpat": f"k{i}", "delta": "-", "node": "Return"}
        c.report(g, True, "guard_none")
        c.report(g, True, "guard_none")
        c.verdict(i % 2 == 0)
    c.close()

    def pct(xs, q):
        xs = sorted(xs)
        return xs[min(len(xs) - 1, int(q * len(xs)))]
    print("host round trip over pipes (perf_counter)")
    for k, unit, mul in (("DECIDE", "µs", 1e6), ("MUTATE", "ms", 1e3), ("KEEP", "ms", 1e3), ("ROLLBACK", "ms", 1e3)):
        xs = c.lat.get(k, [])
        if xs:
            print(f"  {k:9s} n={len(xs):5d}  p50 {pct(xs, .5) * mul:9.1f} {unit}  p99 {pct(xs, .99) * mul:9.1f} {unit}"
                  f"  first {xs[0] * mul:8.1f}  last {xs[-1] * mul:8.1f}")
    print(f"  startup (spawn + set-code seed + eval-current + snapshot): {c.startup_s * 1e3:.0f} ms")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="aura_coder")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bench", help="static vs restart vs adaptive over a shifted stream")
    b.add_argument("--modes", nargs="+", default=["static", "restart", "adaptive", "adaptive-nogate"])
    b.add_argument("--seeds", nargs="+", type=int, default=[0, 1, 2])
    b.add_argument("--n", type=int, default=60)
    b.add_argument("--jobs", type=int, default=1)
    b.add_argument("--out", default="runs")
    b.add_argument("--noise", type=float, default=0.0,
                   help="probability that a reported winning operator is replaced by a wrong one")
    lt = sub.add_parser("latency", help="closed-loop set-code -> query -> mutate -> eval-current inside Aura")
    lt.add_argument("--n", type=int, default=200)
    sub.add_parser("acceptance", help="rebind-correctness checks (aura #4546 #4547 #4550 #4552) on AURA_BIN")
    c = sub.add_parser("corpus", help="print the task stream")
    c.add_argument("--seed", type=int, default=0)
    c.add_argument("--n", type=int, default=60)
    a = ap.parse_args(argv)

    if a.cmd == "bench":
        from .bench import bench, table
        res = bench(a.modes, a.seeds, a.n, a.out, a.jobs, a.noise)
        print(table(res))
        return 0
    if a.cmd == "latency":
        aura, env = aura_env()
        env["N"] = str(a.n)
        env["AURA_CODER_POLICY"] = str(ROOT / "aura" / "policy_seed.aura")
        p = subprocess.run([aura, str(ROOT / "aura" / "closed_loop_bench.aura")], env=env, cwd=str(ROOT),
                           capture_output=True, text=True, timeout=1800)
        for line in p.stdout.splitlines():
            if line.startswith("BENCH "):
                d = json.loads(line[6:])
                print("inside Aura (µs per op, current-time-ms clock, N=%d)" % a.n)
                for k in ("cycle_us", "set_code_eval_us", "query_us", "rebind_us", "eval_current_us",
                          "rebind_eval_us", "decide_us", "snapshot_us", "restore_eval_us"):
                    print(f"  {k:18s} {d[k]:10.1f}")
                host_round_trips(a.n)
                return 0
        print(p.stdout[-2000:], p.stderr[-2000:], file=sys.stderr)
        return 1
    if a.cmd == "acceptance":
        from .acceptance import main as acc
        return acc()
    if a.cmd == "corpus":
        from .corpus import stream
        for t in stream(a.seed, a.n):
            print(t.tid, t.phase)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
