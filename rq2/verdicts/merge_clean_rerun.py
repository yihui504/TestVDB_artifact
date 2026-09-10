# -*- coding: utf-8 -*-
"""Merge cleaned-cognition reruns (11 affected milvus cases x 3 rounds) into the
full-stage matrix. Unaffected cases keep their run_full1/2/3 verdicts; the 11
affected cases take the run_fullc{1,2,3} cleaned verdicts. Outputs per-round
matrices, majority, and the pre/post-cleaning comparison."""
import json, glob, math, os

BASE = r'.paperpilot/phase2-rerun/arms/rq2_3run'
GT = json.load(open(os.path.join(BASE, 'gt_81.json'), encoding='utf-8'))
AFFECTED = ['milvus_010', 'milvus_018', 'milvus_019', 'milvus_021', 'milvus_022',
            'milvus_027', 'milvus_028', 'milvus_032', 'milvus_033', 'milvus_035', 'milvus_037']

def load_glob(pattern):
    v = {}
    for f in glob.glob(os.path.join(BASE, pattern)):
        for line in open(f, encoding='utf-8'):
            if line.strip():
                try:
                    j = json.loads(line); v[j['defect_id']] = j['verdict']
                except Exception:
                    pass
    return v

def matrix(v):
    tp = fp = fn = tn = 0
    for cid, g in GT.items():
        if cid not in v:
            continue
        conf, t = v[cid] == 'CONFIRMED', g == 'T'
        tp += conf and t; fp += conf and not t; fn += (not conf) and t; tn += (not conf) and (not t)
    n = sum(v.get(c) is not None for c in GT)
    return tp, fp, fn, tn, n

def wilson(k, nn, z=1.96):
    if nn == 0: return (0, 0)
    p = k / nn; d = 1 + z * z / nn
    c = (p + z * z / (2 * nn)) / d
    h = z * math.sqrt(p * (1 - p) / nn + z * z / (4 * nn * nn)) / d
    return (round(max(0, c - h), 3), round(min(1, c + h), 3))

dirty = {r: load_glob(f'run_full{r}/verdicts_batch*.jsonl') for r in (1, 2, 3)}
clean = {r: load_glob(f'run_fullc{r}/verdicts_clean.jsonl') for r in (1, 2, 3)}
missing = [r for r in (1, 2, 3) if len(clean[r]) < 11]
if missing:
    raise SystemExit(f'clean reruns incomplete for rounds {missing}')

print('=== 污染版(对照) ===')
for r in (1, 2, 3):
    tp, fp, fn, tn, n = matrix(dirty[r])
    print(f'full {r}: {tp}/{fp}/{fn}/{tn} (n={n})')
print('=== 净化版合并(11 案用 cleaned,其余沿用) ===')
merged = {}
for r in (1, 2, 3):
    v = dict(dirty[r])
    for c in AFFECTED:
        v[c] = clean[r][c]
    merged[r] = v
    tp, fp, fn, tn, n = matrix(v)
    P = tp / (tp + fp) if tp + fp else 0
    R = tp / (tp + fn) if tp + fn else 0
    S = tn / (tn + fp) if tn + fp else 0
    print(f'full-clean {r}: TP={tp} FP={fp} FN={fn} TN={tn} | P={P:.3f} R={R:.3f} FPsup={S:.3f}{wilson(tn, tn + fp)}')
maj = {}
for cid in GT:
    cs = sum(1 for r in (1, 2, 3) if merged[r].get(cid) == 'CONFIRMED')
    maj[cid] = 'CONFIRMED' if cs >= 2 else 'FALSE_POSITIVE'
tp, fp, fn, tn, n = matrix(maj)
print(f'majority-clean: TP={tp} FP={fp} FN={fn} TN={tn} | P={tp/(tp+fp):.3f}{wilson(tp, tp+fp)} R={tp/(tp+fn):.3f}{wilson(tp, tp+fn)} FPsup={tn/(tn+fp):.3f}{wilson(tn, tn+fp)}')
print('=== 逐案变化(污染→净化,majority 口径) ===')
mj_dirty = {c: 'CONFIRMED' if sum(1 for r in (1, 2, 3) if dirty[r].get(c) == 'CONFIRMED') >= 2 else 'FALSE_POSITIVE' for c in GT}
chg = [(c, GT[c], mj_dirty[c], maj[c]) for c in GT if mj_dirty[c] != maj[c]]
for c, g, a, b in chg:
    print(f'  {c}: GT={g} {a} -> {b}')
if not chg:
    print('  (无变化——1.000 suppression 在净化认知下存活)')
json.dump({'merged': {str(r): merged[r] for r in (1, 2, 3)}, 'majority': maj},
          open(os.path.join(BASE, 'majority_fullstage_cleaned.json'), 'w'), indent=1)
print('written majority_fullstage_cleaned.json')
