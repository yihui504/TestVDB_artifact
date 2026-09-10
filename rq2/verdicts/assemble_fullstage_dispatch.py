# -*- coding: utf-8 -*-
"""Assemble full-stage rerun dispatch files (6 batches) mapping each of the 81 cases
to its pack + exact-version source clone + cognition file. Run from repo root after
batch_clone_rq2full.sh reports ALL DONE."""
import json, os

PACK = r'c:\<HOME>\<ARTIFACT_ROOT>\.paperpilot\phase2-rerun\arms\materials_complete'
LOCAL = r'c:\<HOME>\<ARTIFACT_ROOT>\.sourcedeps'
PIPELINE_HOST = r'<PIPELINE_SOURCE>\.sourcedeps'
EXP = r'<PIPELINE_SOURCE>\.sourcedeps'
OUTDIR = r'c:\<HOME>\<ARTIFACT_ROOT>\.paperpilot\phase2-rerun\arms\rq2_3run\run_full1'

def clone_path(vendor, ver):
    v = ver if ver.startswith('v') else 'v' + ver
    if vendor == 'milvus' and ver == '2.3':
        v = 'v2.3.0'
    cands = [os.path.join(LOCAL, vendor, v), os.path.join(PIPELINE_HOST, vendor, v), os.path.join(EXP, vendor, v)]
    for c in cands:
        if os.path.isdir(c):
            return c
    return None

# case -> (vendor, version)
cv = {}
m = json.load(open('.paperpilot/phase2-rerun/defect_id_map.json', encoding='utf-8'))
for cid, info in m.items():
    cv[cid] = (info['vendor'], info['version'])
gt10 = json.load(open('results/rq2_pool81/gt_map_new10.json', encoding='utf-8'))
for cid, info in gt10.items():
    cv[cid] = ('qdrant', info['ver'])

# verify every clone exists
missing = {cid: clone_path(v, ver) for cid, (v, ver) in cv.items() if clone_path(v, ver) is None}
if missing:
    print('MISSING CLONES:', missing)
    raise SystemExit(1)

plan = json.load(open('.paperpilot/phase2-rerun/arms/rq2_3run/batch_plan.json', encoding='utf-8'))
tmpl = open('.paperpilot/phase2-rerun/arms/rq2_3run/dispatch_fullstage_template.md', encoding='utf-8').read()
os.makedirs(OUTDIR, exist_ok=True)
made = 0
for b, cases in plan.items():
    lines = []
    for c in cases:
        v, ver = cv[c]
        lines.append(fr'- {c}: pack={PACK}\{c}.md | source={clone_path(v, ver)}')
    out = os.path.join(OUTDIR, f'verdicts_{b}.jsonl')
    body = tmpl.replace('{CASE_MATERIALS}', '\n'.join(lines)).replace('{OUT_PATH}', out)
    open(os.path.join(OUTDIR, f'{b}_dispatch.txt'), 'w', encoding='utf-8').write(body)
    made += 1
print(f'assembled {made} batch dispatch files -> {OUTDIR}')
