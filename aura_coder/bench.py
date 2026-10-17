"""Benchmark: static vs restart-each-task vs adaptive (vs adaptive without gate) over a shifted task stream."""
from __future__ import annotations

import json
import statistics
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from .agent import Agent
from .corpus import stream
from . import runner

MODES = ("static", "restart", "adaptive", "adaptive-nogate")


def _pct(xs, q):
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def run_one(mode: str, seed: int, n: int, outroot: str, noise: float = 0.0) -> dict:
    out = Path(outroot) / f"{mode}-seed{seed}"
    t0 = time.perf_counter()
    runner.RUNS["n"] = 0
    a = Agent(mode, out, noise=noise, seed=seed)
    for task in stream(seed, n):
        a.run_task(task)
    a.close()
    eps = a.episodes
    third = max(1, n // 3)
    win = [sum(e.solved for e in eps[i:i + third]) / len(eps[i:i + third]) for i in range(0, n, third)][:3]
    solved = sum(e.solved for e in eps)
    task_att = sum(e.attempts for e in eps)
    over = sum(e.pm_attempts + e.gate_attempts for e in eps)
    prov = [p for p in a.prov if p["verdict"] in ("KEEP", "ROLLBACK")]
    lat = a.lat
    res = {
        "mode": mode, "seed": seed, "n": n, "noise": noise, "solved": solved, "solve_rate": solved / n, "window_solve_rate": win,
        "task_attempts": task_att, "overhead_attempts": over,
        "attempts_per_solved": task_att / max(1, solved), "total_attempts_per_solved": (task_att + over) / max(1, solved),
        "mutations": len(prov), "keep": sum(p["verdict"] == "KEEP" for p in prov),
        "rollback": sum(p["verdict"] == "ROLLBACK" for p in prov),
        "final_version": max([p["version"] for p in a.prov] + [0]),
        "decide_us_p50": (_pct(lat.get("DECIDE", []), .5) or 0) * 1e6,
        "decide_us_p99": (_pct(lat.get("DECIDE", []), .99) or 0) * 1e6,
        "mutate_ms_p50": (_pct(lat.get("MUTATE", []), .5) or 0) * 1e3,
        "mutate_ms_max": (max(lat.get("MUTATE", [0])) or 0) * 1e3,
        "rollback_ms_p50": (_pct(lat.get("ROLLBACK", []), .5) or 0) * 1e3,
        "keep_ms_p50": (_pct(lat.get("KEEP", []), .5) or 0) * 1e3,
        "restart_ms_mean": statistics.mean(a.restart_s) * 1e3 if a.restart_s else 0.0,
        "decisions": len(lat.get("DECIDE", [])),
        "test_runs": runner.RUNS["n"],
        "wall_s": time.perf_counter() - t0,
    }
    (out / "metrics.json").write_text(json.dumps(res, indent=1))
    return res


def _mean(rs, k):
    return statistics.mean(r[k] for r in rs)


def table(results: list[dict]) -> str:
    rows = ["| mode | solve rate (mean, min–max) | window 1 / 2 / 3 | attempts / solved (task) | "
            "attempts / solved (incl. learning) | mutations | KEEP / ROLLBACK | decide µs p50 / p99 | "
            "mutate ms p50 | rollback ms p50 | restart ms | wall s |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for mode in MODES:
        rs = [r for r in results if r["mode"] == mode]
        if not rs:
            continue
        sr = [r["solve_rate"] for r in rs]
        w = [statistics.mean(r["window_solve_rate"][i] for r in rs) for i in range(3)]
        rows.append(
            f"| {mode} | {statistics.mean(sr):.1%} ({min(sr):.0%}–{max(sr):.0%}) | "
            f"{w[0]:.0%} / {w[1]:.0%} / {w[2]:.0%} | {_mean(rs, 'attempts_per_solved'):.2f} | "
            f"{_mean(rs, 'total_attempts_per_solved'):.2f} | {_mean(rs, 'mutations'):.1f} | "
            f"{_mean(rs, 'keep'):.1f} / {_mean(rs, 'rollback'):.1f} | "
            f"{_mean(rs, 'decide_us_p50'):.0f} / {_mean(rs, 'decide_us_p99'):.0f} | "
            + (f"{_mean(rs, 'mutate_ms_p50'):.1f}" if _mean(rs, 'mutations') else "–") + " | "
            + (f"{_mean(rs, 'rollback_ms_p50'):.1f}" if _mean(rs, 'rollback') else "–") + " | "
            + (f"{_mean(rs, 'restart_ms_mean'):.0f}" if mode == "restart" else "–")
            + f" | {_mean(rs, 'wall_s'):.0f} |")
    return "\n".join(rows)


def bench(modes, seeds, n, outroot="runs", jobs=1, noise=0.0) -> list[dict]:
    Path(outroot).mkdir(parents=True, exist_ok=True)
    work = [(m, s, n, outroot, noise) for s in seeds for m in modes]
    if jobs > 1:
        with ProcessPoolExecutor(jobs) as ex:
            results = list(ex.map(run_one, *zip(*work)))
    else:
        results = [run_one(*w) for w in work]
    (Path(outroot) / "results.json").write_text(json.dumps(results, indent=1))
    (Path(outroot) / "results.md").write_text(table(results) + "\n")
    return results
