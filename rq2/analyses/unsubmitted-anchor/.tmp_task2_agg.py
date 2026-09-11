"""Aggregate task2 (unsubmitted-stream anchor) verdicts: majority vote, recall, Wilson."""
import json
import glob
import math
import collections

ids_seen = collections.defaultdict(dict)  # case -> run -> verdict
for f in sorted(glob.glob(".paperpilot/phase2-rerun/arms/rq2_3run/run_task2/verdicts_*.jsonl")):
    run = f.split("verdicts_")[1].split("_")[0]
    for line in open(f, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        ids_seen[r["defect_id"]][run] = r["verdict"]

n_runs_expected = 3
complete = {k: v for k, v in ids_seen.items() if len(v) == n_runs_expected}
print(f"cases: {len(ids_seen)} total, {len(complete)} with all 3 runs")


def wilson(k, n, z=1.959964):
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0, c - h), min(1, c + h)


maj = {}
for k, v in complete.items():
    conf = sum(1 for x in v.values() if x == "CONFIRMED")
    maj[k] = "CONFIRMED" if conf * 2 >= n_runs_expected else "FALSE_POSITIVE"

conf_n = sum(1 for k in complete if maj[k] == "CONFIRMED")
n = len(complete)
lo, hi = wilson(conf_n, n)
print(f"\nmajority recall on unsubmitted confirmed stream: {conf_n}/{n} = {conf_n/n:.3f}  Wilson [{lo:.3f},{hi:.3f}]")

unanimous = sum(1 for k, v in ids_seen.items() if len(set(v.values())) == 1 and len(v) == n_runs_expected)
print(f"unanimous (of complete): {unanimous}/{n}")

print("\nper-case (majority):")
for k in sorted(complete):
    conf = sum(1 for x in complete[k].values() if x == "CONFIRMED")
    print(f"  {k}: {'CONFIRMED' if maj[k]=='CONFIRMED' else 'FP':12s} ({conf}/3)")
incomplete = {k: v for k, v in ids_seen.items() if len(v) < n_runs_expected}
if incomplete:
    print("\nincomplete (excluded from majority):")
    for k, v in incomplete.items():
        print(f"  {k}: {dict(v)}")
