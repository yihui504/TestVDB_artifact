"""Flat-judge arm: final analysis — integrity, per-run, majority, McNemar vs other arms."""
import json, glob, os, math, collections

BASE = ".paperpilot/phase2-rerun/arms/rq2_3run"
gt = json.load(open(os.path.join(BASE, "gt_81.json"), encoding="utf-8"))
ids = sorted(gt)


def load(p):
    o = {}
    for f in sorted(glob.glob(os.path.join(BASE, p))):
        for l in open(f, encoding="utf-8"):
            l = l.strip()
            if l:
                r = json.loads(l)
                o[r["defect_id"]] = r["verdict"]
    return o


def wilson(k, n, z=1.959964):
    p = k / n; d = 1 + z * z / n; c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0, c - h), min(1, c + h))


def maj(per):
    return {i: ("CONFIRMED" if sum(1 for r in per if per[r][i] == "CONFIRMED") * 2 >= 3 else "FALSE_POSITIVE")
            for i in ids}


def report(m, label):
    tp = sum(1 for i in ids if gt[i] == "T" and m[i] == "CONFIRMED")
    fp = sum(1 for i in ids if gt[i] == "F" and m[i] == "CONFIRMED")
    fn, tn = 51 - tp, 30 - fp
    lo, hi = wilson(tn, 30)
    pr = tp / (tp + fp) if tp + fp else 0
    print(f"  {label:22s} TP={tp:2d} FP={fp} FN={fn:2d} TN={tn:2d} | recall={tp/51:.3f} supp={tn/30:.3f} [{lo:.3f},{hi:.3f}] prec={pr:.3f}")


flat = {r: load(f"run_flat{r}/verdicts_batch*.jsonl") for r in (1, 2, 3)}
for r in flat:
    assert len(flat[r]) == 81 and len(set(flat[r])) == 81, r
flatM = maj(flat)

print("== flat-judge arm (single prompt, no scaffolding, pack + optional source) ==")
for r in (1, 2, 3):
    report(flat[r], f"flat run {r}")
report(flatM, "flat majority")
agree3 = sum(1 for i in ids if len({flat[r][i] for r in (1, 2, 3)}) == 1)
print(f"  unanimous: {agree3}/81 ({agree3/81:.1%})")

# references
core = {r: load(f"{r}/verdicts_batch*.jsonl") for r in ("run1", "run2", "run3")}
coreM = maj(core)
fullR = {r: load(f"run_full{r[-1]}/verdicts_batch*.jsonl") for r in ("full1", "full2", "full3")}
fullM = maj(fullR)
donlyR = {r: load(f"{r}/verdicts_batch*.jsonl") for r in ("run_donly1", "run_donly2", "run_donly3")}
donlyM = maj(donlyR)

print("\n== side-by-side (majorities) ==")
report(coreM, "contract core")
report(donlyM, "source-only (D)")
report(flatM, "flat judge")
report(fullM, "full stage")


def mcnemar(a, b):
    x = sum(1 for i in ids if (b[i] == "CONFIRMED") == (gt[i] == "T") and (a[i] == "CONFIRMED") != (gt[i] == "T"))
    y = sum(1 for i in ids if (a[i] == "CONFIRMED") == (gt[i] == "T") and (b[i] == "CONFIRMED") != (gt[i] == "T"))
    n = x + y
    p = 1.0 if n == 0 else min(1.0, 2 * sum(math.comb(n, k) for k in range(0, min(x, y) + 1)) / 2 ** n)
    return x, y, p


print("\n== McNemar on correctness ==")
for la, a, lb, b in (("core", coreM, "flat", flatM), ("flat", flatM, "donly", donlyM),
                     ("flat", flatM, "full", fullM), ("donly", donlyM, "full", fullM)):
    x, y, p = mcnemar(a, b)
    print(f"  {la:6s} vs {lb:6s}: {lb}-better={x:2d} {la}-better={y:2d} p={p:.4f}")

# flat vs D-only case-level agreement
agree = sum(1 for i in ids if flatM[i] == donlyM[i])
print(f"\nflat vs source-only majority case agreement: {agree}/81")
diffs = [i for i in ids if flatM[i] != donlyM[i]]
print("differing:", [(i, gt[i], donlyM[i][:4], flatM[i][:4]) for i in diffs][:15])
