"""Summary over protocol series: one row per animal with the results of every assay,
values per mg of protein, and group statistics (Welch t-test and Mann–Whitney U)."""
from __future__ import annotations

import json
import math
from itertools import combinations
from pathlib import Path

from .protocol import NAN, Run, _clean, _mean, _sd, isnum, welch

# what to take from each built-in protocol: (protocol id, result var, column label, unit)
KNOWN = [
    ("mda", "C", "МДА", "мкмоль/л"),
    ("catalase", "A", "Каталаза", "мкмоль/хв/мл"),
    ("sod", "uo_ml", "СОД", "у.о./мл"),
    ("sh", "SH", "SH-групи", "мкмоль/л"),
    ("sh", "Hb", "Вільний Hb", "мг/л"),
    ("hemolysis", "Hb", "Вільний Hb", "мг/л"),
    ("bradford", "C", "Білок (Бредфорд)", "мг/мл"),
    ("lowry", "C", "Білок (Лоурі)", "мг/мл"),
]
# values per mg protein: (column, numerator label, factor, unit)
PER_PROTEIN = [
    ("МДА", 1.0, "нмоль/мг білка"),             # мкмоль/л = нмоль/мл; / (мг/мл) = нмоль/мг
    ("Каталаза", 1.0, "мкмоль/хв/мг білка"),
    ("СОД", 1.0, "у.о./мг білка"),
    ("SH-групи", 1.0, "мкмоль/г білка"),        # мкмоль/л / (г/л)
]


def mann_whitney(x, y) -> tuple[float, float]:
    """U and the two-sided p (exact permutation for n1 + n2 ≤ 20, else normal approximation)."""
    x, y = _clean(x), _clean(y)
    n1, n2 = len(x), len(y)
    if n1 == 0 or n2 == 0:
        return NAN, NAN
    allv = sorted((v, g) for g, vs in ((0, x), (1, y)) for v in vs)
    ranks = {}
    i = 0
    ties = []
    while i < len(allv):
        j = i
        while j + 1 < len(allv) and allv[j + 1][0] == allv[i][0]:
            j += 1
        r = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[k] = r
        if j > i:
            ties.append(j - i + 1)
        i = j + 1
    r1 = sum(ranks[k] for k, (_, g) in enumerate(allv) if g == 0)
    u1 = r1 - n1 * (n1 + 1) / 2
    u = min(u1, n1 * n2 - u1)
    if n1 + n2 <= 20:
        # exact permutation distribution of U over the actual (mid-)ranks, ties included
        rk = [ranks[k] for k in range(len(allv))]
        total = 0
        le = 0
        for comb in combinations(range(n1 + n2), n1):
            uu = sum(rk[k] for k in comb) - n1 * (n1 + 1) / 2
            total += 1
            if min(uu, n1 * n2 - uu) <= u + 1e-9:
                le += 1
        return u, min(1.0, le / total)
    n = n1 + n2
    mu = n1 * n2 / 2
    tie = sum(t ** 3 - t for t in ties)
    sigma = math.sqrt(n1 * n2 / 12 * ((n + 1) - tie / (n * (n - 1))))
    if sigma == 0:
        return u, NAN
    z = (abs(u1 - mu) - 0.5) / sigma
    return u, math.erfc(z / math.sqrt(2))


def load_runs(paths) -> list[Run]:
    runs = []
    for p in paths:
        try:
            runs.append(Run.from_json(json.loads(Path(p).read_text(encoding="utf-8"))))
        except Exception:
            continue
    return runs


def build(runs: list[Run], protein: str = "auto") -> dict:
    """{columns: [(label, unit)], animals: [{code, group, values{label: v}}], stats: [...]}"""
    animals: dict[str, dict] = {}
    columns: list[tuple[str, str]] = []

    def put(code, group, label, unit, v):
        a = animals.setdefault(code, {"code": code, "group": group, "values": {}})
        if group and not a["group"]:
            a["group"] = group
        if (label, unit) not in columns:
            columns.append((label, unit))
        if isnum(v):
            a["values"][label] = v

    known_ids = {k[0] for k in KNOWN}
    # later runs override earlier ones for the same animal and assay
    for run in sorted(runs, key=lambda r: r.started):
        c = run.compute()
        pid = run.p.get("id", "")
        base = pid.split("_my")[0]
        for s in c["samples"]:
            if not s["measured"]:
                continue
            if base in known_ids:
                for kid, var, label, unit in KNOWN:
                    if kid == base:
                        put(s["code"], s["group"], label, unit, s["res"].get(var))
            else:
                for r in run.p.get("results", []):
                    put(s["code"], s["group"], f"{run.p['name']}: {r['label']}", r.get("unit", ""),
                        s["res"].get(r["var"]))
    # per mg protein
    prot_label = None
    for lab in ("Білок (Бредфорд)", "Білок (Лоурі)"):
        if protein in ("auto", lab) and any(lab in a["values"] for a in animals.values()):
            prot_label = lab
            break
    if prot_label:
        for name, factor, unit in PER_PROTEIN:
            if not any(name in a["values"] for a in animals.values()):
                continue
            col = f"{name} / білок"
            for a in animals.values():
                v, p = a["values"].get(name), a["values"].get(prot_label)
                put(a["code"], a["group"], col, unit, v / p * factor if isnum(v) and isnum(p) and p else NAN)
    # order columns as KNOWN, then the rest
    order = [k[2] for k in KNOWN]
    columns.sort(key=lambda c: (order.index(c[0]) if c[0] in order else len(order), ))
    groups = []
    for a in animals.values():
        if a["group"] and a["group"] not in groups:
            groups.append(a["group"])
    ref = "К" if "К" in groups else (groups[0] if groups else None)
    stats = []
    for label, unit in columns:
        row = {"label": label, "unit": unit, "groups": {}, "ref": ref}
        for g in groups:
            vals = [a["values"].get(label) for a in animals.values() if a["group"] == g]
            vals = _clean([v for v in vals if isnum(v)])
            row["groups"][g] = {"n": len(vals), "mean": _mean(vals), "sd": _sd(vals), "vals": vals}
        for g in groups:
            if g == ref:
                continue
            a, b = row["groups"][ref], row["groups"][g]
            _, _, p = welch(a["vals"], b["vals"])
            _, pmw = mann_whitney(a["vals"], b["vals"])
            b["change"] = (b["mean"] - a["mean"]) / a["mean"] if a["mean"] else NAN
            b["p"], b["p_mw"] = p, pmw
        stats.append(row)
    return {"columns": columns, "animals": sorted(animals.values(), key=lambda a: (a["group"], a["code"])),
            "stats": stats, "groups": groups, "ref": ref, "protein": prot_label}
