"""Final aggregation for the independent D-only arm (3 runs) vs core/full/post-hoc."""
import json, glob, os, math, collections

BASE = ".paperpilot/phase2-rerun/arms/rq2_3run"
gt = json.load(open(os.path.join(BASE, "gt_81.json"), encoding="utf-8"))
ids = sorted(gt)


def load_run(pattern):
    out = {}
    for f in sorted(glob.glob(os.path.join(BASE, pattern))):
        for line in open(f, encoding="utf-8"):
            line = line.strip()
            if line:
                r = json.loads(line)
                out[r["defect_id"]] = r
    return out


def wilson(k, n, z=1.959964):
    p = k / n; d = 1 + z * z / n; c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0, c - h), min(1, c + h))


def confusion(verdicts, label):
    tp = fp = fn = tn = 0
    for i in ids:
        pos = (verdicts[i] == "CONFIRMED")
        if gt[i] == "T":
            tp += pos; fn += (not pos)
        else:
            fp += pos; tn += (not pos)
    lo, hi = wilson(tn, 30)
    print(f"  {label:<26} TP={tp:2d} FP={fp} FN={fn:2d} TN={tn:2d} | recall={tp/51:.3f} supp={tn/30:.3f} [{lo:.3f},{hi:.3f}] prec={tp/(tp+fp) if tp+fp else 0:.3f}")
    return {i: verdicts[i] for i in ids}


def maj(per_run):
    return {i: ("CONFIRMED" if sum(1 for r in per_run if per_run[r][i] == "CONFIRMED") * 2 >= 3 else "FALSE_POSITIVE") for i in ids}


def mcnemar_correct(a, b):
    x = sum(1 for i in ids if (b[i] == "CONFIRMED") == (gt[i] == "T") and (a[i] == "CONFIRMED") != (gt[i] == "T"))
    y = sum(1 for i in ids if (a[i] == "CONFIRMED") == (gt[i] == "T") and (b[i] == "CONFIRMED") != (gt[i] == "T"))
    n = x + y
    p = 1.0 if n == 0 else min(1.0, 2 * sum(math.comb(n, k) for k in range(0, min(x, y) + 1)) / 2 ** n)
    return x, y, p


# --- independent D-only arm ---
donly = {}
for r in ("run_donly1", "run_donly2", "run_donly3"):
    recs = load_run(f"{r}/verdicts_batch*.jsonl")
    assert len(recs) == 81, (r, len(recs))
    donly[r] = {k: v["verdict"] for k, v in recs.items()}
    donly[r + "_recs"] = recs

print("== independent D-only arm, 3 runs ==")
for r in ("run_donly1", "run_donly2", "run_donly3"):
    confusion(donly[r], r)
donlyM = maj({r: donly[r] for r in ("run_donly1", "run_donly2", "run_donly3")})
confusion(donlyM, "donly majority")
agree3 = sum(1 for i in ids if len({donly[r][i] for r in ("run_donly1", "run_donly2", "run_donly3")}) == 1)
print(f"  unanimous across 3 runs: {agree3}/81 ({agree3/81:.1%})")

# --- references ---
core = {r: {k: v["verdict"] for k, v in load_run(f"{r}/verdicts_batch*.jsonl").items()} for r in ("run1", "run2", "run3")}
coreM = maj(core)
fullR = {r: load_run(f"run_full{r[-1]}/verdicts_batch*.jsonl") for r in ("full1", "full2", "full3")}
fullM = maj({r: {k: v["verdict"] for k, v in recs.items()} for r, recs in fullR.items()})
post = maj({r: {k: ("CONFIRMED" if v["perspectives"]["D"] == "validation_absent" else "FALSE_POSITIVE") for k, v in recs.items()} for r, recs in fullR.items()})

print("\n== side-by-side ==")
confusion(coreM, "core majority")
confusion(post, "post-hoc D-only maj")
confusion(donlyM, "D-only INDEP maj")
confusion(fullM, "full majority")

print("\n== McNemar on correctness (majorities) ==")
for la, a, lb, b in (("core", coreM, "donly", donlyM), ("donly", donlyM, "full", fullM), ("core", coreM, "full", fullM)):
    x, y, p = mcnemar_correct(a, b)
    print(f"  {la:6s} vs {lb:6s}: {lb}-better={x:2d} {la}-better={y:2d} exact p={p:.4f}")

print("\n== D-only indep maj vs post-hoc maj, per case ==")
diff = [(i, gt[i], donlyM[i], post[i]) for i in ids if donlyM[i] != post[i]]
print(f"agreement {81-len(diff)}/81; disagreements:")
for i, g, a, b in diff:
    dvals = [fullR[r][i]["perspectives"]["D"] for r in ("full1", "full2", "full3")]
    dvals_i = [donly[f"run_donly{k}_recs"][i]["d_outcome"] for k in ("1", "2", "3")]
    print(f"  {i}: gt={g} indep={a} posthoc={b} | full D fields={dvals} | indep D outcomes={dvals_i}")
