"""Deterministic corpus of small buggy Python functions + tests, and a task stream with distribution shift.

Each template is a correct function plus bug injections (class -> (correct fragment, buggy fragment)).
A task is one (template, bug class) pair, renamed per seed so the stream is not a literal replay.

Bug classes
  phase A (the seed policy knows these): obo, cmp, arith
  phase B (appear mid-stream):           none_guard, empty_guard, import
  phase C (appear late):                 type_cast, wrong_return, swap_args
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

PHASE_A = ("obo", "cmp", "arith")
PHASE_B = ("none_guard", "empty_guard", "import")
PHASE_C = ("type_cast", "wrong_return", "swap_args")
ALL_CLASSES = PHASE_A + PHASE_B + PHASE_C


@dataclass(frozen=True)
class Template:
    name: str
    src: str                      # correct source; function named `f_<name>` is renamed to `fn`
    tests: tuple                  # ((args tuple), expected)
    bugs: dict = field(default_factory=dict)   # class -> (good fragment, bad fragment)


T = Template
TEMPLATES: tuple[Template, ...] = (
    T("sum_to", """
def fn(n):
    total = 0
    for i in range(1, n + 1):
        total += i
    return total
""", (((4,), 10), ((1,), 1), ((0,), 0), ((10,), 55)),
      {"obo": ("range(1, n + 1)", "range(1, n)"), "arith": ("total += i", "total -= i")}),
    T("count_above", """
def fn(xs, t):
    count = 0
    for x in xs:
        if x > t:
            count += 1
    return count
""", ((([1, 5, 3, 7], 3), 2), (([3, 3, 4], 3), 1), (([], 1), 0)),
      {"cmp": ("x > t", "x >= t")}),
    T("clamp", """
def fn(x, lo, hi):
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x
""", (((5, 0, 10), 5), ((-3, 0, 10), 0), ((12, 0, 10), 10), ((0, 0, 10), 0)),
      {"cmp": ("x < lo", "x > lo")}),
    T("mean", """
def fn(xs):
    if not xs:
        return 0
    return sum(xs) / len(xs)
""", ((([2, 4, 6],), 4.0), (([5],), 5.0), (([],), 0)),
      {"empty_guard": ("    if not xs:\n        return 0\n", ""), "arith": ("sum(xs) / len(xs)", "sum(xs) * len(xs)")}),
    T("first_word", """
def fn(s):
    if s is None:
        return ''
    parts = s.split()
    if not parts:
        return ''
    return parts[0]
""", ((("hello world",), "hello"), (("  a  b",), "a"), ((None,), ""), (("",), "")),
      {"none_guard": ("    if s is None:\n        return ''\n", ""),
       "empty_guard": ("    if not parts:\n        return ''\n", "")}),
    T("last", """
def fn(xs):
    if not xs:
        return None
    return xs[len(xs) - 1]
""", ((([1, 2, 3],), 3), ((["a"],), "a"), (([],), None)),
      {"obo": ("xs[len(xs) - 1]", "xs[len(xs)]"), "empty_guard": ("    if not xs:\n        return None\n", "")}),
    T("hypot", """
import math


def fn(a, b):
    return math.sqrt(a * a + b * b)
""", (((3, 4), 5.0), ((0, 0), 0.0), ((5, 12), 13.0)),
      {"import": ("import math\n", ""), "arith": ("a * a + b * b", "a * a - b * b")}),
    T("tag", """
def fn(name, n):
    return name + '-' + str(n)
""", ((("job", 3), "job-3"), (("x", 10), "x-10")),
      {"type_cast": ("str(n)", "n")}),
    T("max_gap", """
def fn(xs):
    if len(xs) < 2:
        return 0
    best = 0
    for i in range(len(xs) - 1):
        best = max(best, xs[i + 1] - xs[i])
    return best
""", ((([1, 4, 6],), 3), (([5],), 0), (([1, 2, 10, 11],), 8), (([1, 2, 3, 10],), 7)),
      {"obo": ("range(len(xs) - 1)", "range(len(xs) - 2)"), "arith": ("xs[i + 1] - xs[i]", "xs[i + 1] + xs[i]")}),
    T("word_lengths", """
def fn(words):
    if words is None:
        return []
    return [len(w) for w in words]
""", (((["ab", "c"],), [2, 1]), (([],), []), ((None,), [])),
      {"none_guard": ("    if words is None:\n        return []\n", "")}),
    T("divmod_q", """
def fn(a, b):
    q = a // b
    r = a % b
    return q
""", (((7, 2), 3), ((9, 3), 3), ((1, 5), 0)),
      {"wrong_return": ("    return q", "    return r"), "arith": ("q = a // b", "q = a * b")}),
    T("scale", """
def fn(xs):
    m = max(xs)
    out = [x / m for x in xs]
    return out
""", ((([1, 2, 4],), [0.25, 0.5, 1.0]), (([5],), [1.0])),
      {"wrong_return": ("    return out", "    return xs")}),
    T("power", """
def fn(b, e):
    return pow(b, e)
""", (((2, 3), 8), ((3, 2), 9), ((5, 1), 5)),
      {"swap_args": ("pow(b, e)", "pow(e, b)")}),
    T("minus", """
def sub(a, b):
    return a - b


def fn(x, y):
    return sub(x, y) * 2
""", (((5, 3), 4), ((1, 4), -6), ((0, 0), 0)),
      {"swap_args": ("sub(x, y)", "sub(y, x)"), "arith": ("return a - b", "return a + b")}),
    T("join_path", """
import os


def fn(d, name):
    return os.path.join(d, name)
""", ((("a", "b"), "a/b"), (("/x", "y.txt"), "/x/y.txt")),
      {"import": ("import os\n", ""), "swap_args": ("os.path.join(d, name)", "os.path.join(name, d)")}),
    T("digits", """
import re


def fn(s):
    return re.findall('[0-9]+', s)
""", ((("a1b22",), ["1", "22"]), (("none",), [])),
      {"import": ("import re\n", "")}),
    T("index_of", """
def fn(xs, v):
    for i in range(len(xs)):
        if xs[i] == v:
            return i
    return -1
""", ((([4, 5, 6], 6), 2), (([4], 4), 0), (([1, 2], 9), -1)),
      {"obo": ("range(len(xs))", "range(len(xs) - 1)")}),
    T("is_sorted", """
def fn(xs):
    for i in range(len(xs) - 1):
        if xs[i] > xs[i + 1]:
            return False
    return True
""", ((([1, 2, 2, 3],), True), (([3, 1],), False), (([],), True)),
      {"cmp": ("xs[i] > xs[i + 1]", "xs[i] >= xs[i + 1]")}),
    T("avg_len", """
def fn(words):
    if not words:
        return 0
    total = 0
    for w in words:
        total += len(w)
    return total / len(words)
""", (((["ab", "abcd"],), 3.0), (([],), 0)),
      {"empty_guard": ("    if not words:\n        return 0\n", ""), "arith": ("total += len(w)", "total -= len(w)")}),
    T("lookup", """
def fn(d, k):
    if d is None:
        return None
    if k in d:
        return d[k]
    return None
""", ((({"a": 1}, "a"), 1), (({"a": 1}, "b"), None), ((None, "a"), None)),
      {"none_guard": ("    if d is None:\n        return None\n", "")}),
    T("label", """
def fn(prefix, count):
    return prefix + ':' + str(count) + ' items'
""", ((("box", 2), "box:2 items"), (("", 0), ":0 items")),
      {"type_cast": ("str(count)", "count")}),
    T("total_len", """
def fn(words):
    n = 0
    for w in words:
        n += len(w)
    joined = ''.join(words)
    return n
""", (((["ab", "c"],), 3), (([],), 0)),
      {"wrong_return": ("    return n", "    return joined")}),
    T("in_range", """
def fn(x, lo, hi):
    return lo <= x and x < hi
""", (((3, 3, 5), True), ((5, 3, 5), False), ((4, 3, 5), True)),
      {"cmp": ("lo <= x", "lo < x")}),
    T("tail_sum", """
def fn(xs, k):
    total = 0
    for i in range(len(xs) - k, len(xs)):
        total += xs[i]
    return total
""", ((([1, 2, 3, 4], 2), 7), (([5], 1), 5), (([1, 2], 0), 0)),
      {"obo": ("range(len(xs) - k, len(xs))", "range(len(xs) - k, len(xs) - 1)")}),
    T("ratio", """
def fn(a, b):
    if b == 0:
        return 0
    return a / b
""", (((6, 3), 2.0), ((1, 0), 0), ((5, 2), 2.5)),
      {"swap_args": ("return a / b", "return b / a")}),
)


@dataclass(frozen=True)
class Task:
    tid: str
    template: str
    bug: str
    phase: str
    source: str        # buggy
    fixed: str         # reference
    tests: tuple


def make_task(t: Template, bug: str, tid: str) -> Task:
    good, bad = t.bugs[bug]
    src = t.src.lstrip("\n")
    if good not in src:
        raise ValueError(f"{t.name}/{bug}: fragment not found")
    buggy = src.replace(good, bad, 1)
    phase = "A" if bug in PHASE_A else "B" if bug in PHASE_B else "C"
    return Task(tid, t.name, bug, phase, buggy, src, t.tests)


def all_variants() -> list[Task]:
    return [make_task(t, b, f"{t.name}/{b}") for t in TEMPLATES for b in t.bugs]


def stream(seed: int = 0, n: int = 60) -> list[Task]:
    """Task stream with distribution shift.

    first third: phase A only; second third: 40% A / 60% B; last third: 30% A / 30% B / 40% C.
    """
    rng = random.Random(seed)
    by = {}
    for v in all_variants():
        by.setdefault(v.bug, []).append(v)
    out = []
    for i in range(n):
        frac = i / n
        if frac < 1 / 3:
            mix = {"A": 1.0}
        elif frac < 2 / 3:
            mix = {"A": 0.4, "B": 0.6}
        else:
            mix = {"A": 0.3, "B": 0.3, "C": 0.4}
        r, acc, phase = rng.random(), 0.0, "A"
        for ph, w in mix.items():
            acc += w
            if r < acc:
                phase = ph
                break
        classes = {"A": PHASE_A, "B": PHASE_B, "C": PHASE_C}[phase]
        bug = rng.choice(classes)
        v = rng.choice(by[bug])
        out.append(Task(f"{i:03d}:{v.tid}", v.template, v.bug, v.phase, v.source, v.fixed, v.tests))
    return out
