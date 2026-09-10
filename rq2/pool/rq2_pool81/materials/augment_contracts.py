# -*- coding: utf-8 -*-
"""Augment material packs: append parameter-matched contract rows from the FULL
per-vendor contract into each pack's expected section. Adds evidence; removes nothing.
Run from repo root."""
import json, re, os, glob

def load_rows(p):
    d = json.load(open(p, encoding='utf-8'))
    rows = []
    for k in ('constraints', 'assertions', 'behavioral_contracts', 'state_invariants'):
        v = d.get(k, {})
        if isinstance(v, dict):
            for g in v.values():
                if isinstance(g, list): rows += [r for r in g if isinstance(r, dict)]
        elif isinstance(v, list):
            rows += [r for r in v if isinstance(r, dict)]
    return rows

ROWS = {
    'milvus':  load_rows(r'<PIPELINE_SOURCE>\results\milvus\v2.6.17\structured_contract.json'),
    'qdrant':  load_rows(r'<PIPELINE_SOURCE>\results\qdrant\v1.18.2\structured_contract.json'),
    'weaviate': load_rows(r'<PIPELINE_SOURCE>\results\weaviate\1.38.0\structured_contract.json'),
}
print({k: len(v) for k, v in ROWS.items()})

STOP = {'result', 'status', 'time', 'points', 'class', 'name', 'text', 'true', 'false', 'error', 'payload'}
AUG = 0
for f in sorted(glob.glob('.paperpilot/phase2-rerun/arms/materials_complete/*.md')):
    cid = os.path.basename(f)[:-3]
    vendor = cid.split('_')[0]
    txt = open(f, encoding='utf-8').read()
    if '--- 补充契约行' in txt:
        continue
    obs = txt.split('--- 观察到的行为')[1].split('--- 契约依据')[0] if '--- 观察到的行为' in txt else ''
    params = set(m.group(1) for m in re.finditer(r'"(\w{3,40})"\s*:', obs)) - STOP
    # 参数在完整契约中的匹配行(按参数名出现在 description/assertion)
    hits, seen = [], set()
    for p in sorted(params):
        for r in ROWS[vendor]:
            rid = r.get('constraint_id') or r.get('assertion_id') or id(r)
            if rid in seen: continue
            t = json.dumps(r, ensure_ascii=False).lower()
            if p.lower() in t:
                hits.append(r); seen.add(rid)
    if not hits:
        continue
    # 去重并限量
    uniq, ids = [], set()
    for r in hits:
        rid = r.get('constraint_id') or r.get('assertion_id')
        if rid not in ids:
            uniq.append(r); ids.add(rid)
    uniq = uniq[:14]
    block = ('\n\n--- 补充契约行（全契约参数匹配，2026-09-09 组装；判定可参照，不替代上方契约依据） ---\n'
             + '\n'.join(json.dumps(r, ensure_ascii=False) for r in uniq))
    txt = txt.rstrip() + block + '\n'
    open(f, 'w', encoding='utf-8').write(txt)
    AUG += 1
print(f'augmented {AUG} packs')
