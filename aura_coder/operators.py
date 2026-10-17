"""AST-level repair operators (data plane). Each operator yields candidate patched sources.

Candidates within one operator are ordered by distance to the failing line (if known), so the *policy*
decides which operator family to try, and the data plane decides where.
"""
from __future__ import annotations

import ast
import copy
import re
from typing import Callable, Iterator

STDLIB_MODULES = {"math", "os", "re", "json", "itertools", "collections", "string", "random", "functools"}
GUARD_DEFAULTS = ("0", "None", "''", "[]")


def _fn_params(tree: ast.Module) -> list[str]:
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name == "fn":
            return [a.arg for a in n.args.args]
    return []


def _sites(tree, pred) -> list[ast.AST]:
    return [n for n in ast.walk(tree) if pred(n)]


def _mutate_each(src: str, pred, edits: Callable[[ast.AST], list[Callable[[ast.AST], None]]], line: int):
    """For every node matching pred (ordered by |lineno - line|) and every edit, yield the edited source."""
    tree = ast.parse(src)
    sites = _sites(tree, pred)
    order = sorted(range(len(sites)), key=lambda i: (abs(getattr(sites[i], "lineno", 0) - line) if line else 0, i))
    seen = set()
    for i in order:
        for k, _ in enumerate(edits(sites[i])):
            t2 = ast.parse(src)
            s2 = _sites(t2, pred)[i]
            edits(s2)[k](s2)
            out = ast.unparse(ast.fix_missing_locations(t2)) + "\n"
            if out not in seen:
                seen.add(out)
                yield out


def _is_range(n):
    return isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "range" and n.args


def _bump(delta):
    def edit(n):
        stop = n.args[-1] if len(n.args) > 1 else n.args[0]
        new = ast.BinOp(stop, ast.Add() if delta > 0 else ast.Sub(), ast.Constant(1))
        if len(n.args) > 1:
            n.args[-1] = new
        else:
            n.args[0] = new
    return edit


def range_bound_inc(src, f):
    return _mutate_each(src, _is_range, lambda n: [_bump(+1)], f.get("line", 0))


def range_bound_dec(src, f):
    return _mutate_each(src, _is_range, lambda n: [_bump(-1)], f.get("line", 0))


def index_shift(src, f):
    def pred(n):
        return isinstance(n, ast.Subscript) and not isinstance(n.slice, ast.Slice)

    def mk(d):
        def e(n):
            n.slice = ast.BinOp(n.slice, ast.Sub() if d < 0 else ast.Add(), ast.Constant(1))
        return e
    return _mutate_each(src, pred, lambda n: [mk(-1), mk(+1)], f.get("line", 0))


_STRICT = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt}
_FLIP = {ast.Lt: ast.Gt, ast.Gt: ast.Lt, ast.LtE: ast.GtE, ast.GtE: ast.LtE}


def _cmp_op(table):
    def pred(n):
        return isinstance(n, ast.Compare) and type(n.ops[0]) in table

    def e(n):
        n.ops[0] = table[type(n.ops[0])]()
    return pred, e


def cmp_strict_toggle(src, f):
    pred, e = _cmp_op(_STRICT)
    return _mutate_each(src, pred, lambda n: [e], f.get("line", 0))


def cmp_flip(src, f):
    pred, e = _cmp_op(_FLIP)
    return _mutate_each(src, pred, lambda n: [e], f.get("line", 0))


_ARITH = {ast.Add: (ast.Sub,), ast.Sub: (ast.Add,), ast.Mult: (ast.Div, ast.FloorDiv), ast.Div: (ast.Mult,),
          ast.FloorDiv: (ast.Mult,)}


def binop_swap(src, f):
    def pred(n):
        return isinstance(n, (ast.BinOp, ast.AugAssign)) and type(n.op) in _ARITH and not (
            isinstance(n, ast.BinOp) and isinstance(n.right, ast.Constant) and n.right.value == 1)

    def edits(n):
        return [(lambda m, c=c: setattr(m, "op", c())) for c in _ARITH[type(n.op)]]
    return _mutate_each(src, pred, edits, f.get("line", 0))


def _guard(src, test_tpl):
    tree = ast.parse(src)
    for p in _fn_params(tree):
        for d in GUARD_DEFAULTS:
            t2 = ast.parse(src)
            fn = next(n for n in t2.body if isinstance(n, ast.FunctionDef) and n.name == "fn")
            fn.body.insert(0, ast.parse(f"if {test_tpl.format(p=p)}:\n    return {d}\n").body[0])
            yield ast.unparse(ast.fix_missing_locations(t2)) + "\n"


def guard_none(src, f):
    return _guard(src, "{p} is None")


def guard_empty(src, f):
    """Guard on an empty param, or on an empty local right after it is assigned."""
    yield from _guard(src, "not {p}")
    tree = ast.parse(src)
    fn = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "fn"), None)
    if fn is None:
        return
    for i, st in enumerate(fn.body):
        if isinstance(st, ast.Assign) and isinstance(st.targets[0], ast.Name):
            for d in GUARD_DEFAULTS:
                t2 = ast.parse(src)
                fn2 = next(n for n in t2.body if isinstance(n, ast.FunctionDef) and n.name == "fn")
                fn2.body.insert(i + 1, ast.parse(f"if not {st.targets[0].id}:\n    return {d}\n").body[0])
                yield ast.unparse(ast.fix_missing_locations(t2)) + "\n"


def add_import(src, f):
    m = re.search(r"name '(\w+)' is not defined", f.get("msg", ""))
    names = [m.group(1)] if m else []
    if not names:   # without a NameError: any free module-like name
        tree = ast.parse(src)
        bound = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
        names = sorted({n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id in STDLIB_MODULES} - bound)
    for name in names:
        if name in STDLIB_MODULES:
            yield f"import {name}\n" + src


def cast_str(src, f):
    def pred(n):
        return isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add)

    def wrap(side):
        def e(n):
            setattr(n, side, ast.Call(ast.Name("str", ast.Load()), [getattr(n, side)], []))
        return e
    return _mutate_each(src, pred, lambda n: [wrap("right"), wrap("left")], f.get("line", 0))


def return_swap(src, f):
    tree = ast.parse(src)
    names = sorted({t.id for n in ast.walk(tree) if isinstance(n, ast.Assign) for t in n.targets
                    if isinstance(t, ast.Name)} | set(_fn_params(tree)))

    def pred(n):
        return isinstance(n, ast.Return) and isinstance(n.value, ast.Name)

    def edits(n):
        return [(lambda m, v=v: setattr(m, "value", ast.Name(v, ast.Load()))) for v in names if v != n.value.id]
    return _mutate_each(src, pred, edits, f.get("line", 0))


def swap_call_args(src, f):
    def pred(n):
        return isinstance(n, ast.Call) and len(n.args) >= 2 and not _is_range(n)

    def e(n):
        n.args[0], n.args[1] = n.args[1], n.args[0]
    def pred2(n):
        return isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Div, ast.Sub, ast.FloorDiv))

    def e2(n):
        n.left, n.right = n.right, n.left
    yield from _mutate_each(src, pred, lambda n: [e], f.get("line", 0))
    yield from _mutate_each(src, pred2, lambda n: [e2], f.get("line", 0))


OPERATORS: dict[str, Callable[[str, dict], Iterator[str]]] = {
    "range_bound_inc": range_bound_inc,
    "range_bound_dec": range_bound_dec,
    "index_shift": index_shift,
    "cmp_strict_toggle": cmp_strict_toggle,
    "cmp_flip": cmp_flip,
    "binop_swap": binop_swap,
    "return_swap": return_swap,
    "swap_call_args": swap_call_args,
    "cast_str": cast_str,
    "guard_empty": guard_empty,
    "guard_none": guard_none,
    "add_import": add_import,
}


def candidates(src: str, feats: dict, op: str) -> list[str]:
    try:
        return list(OPERATORS[op](src, feats))
    except SyntaxError:
        return []
