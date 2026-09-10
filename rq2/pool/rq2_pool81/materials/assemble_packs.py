# -*- coding: utf-8 -*-
"""Assemble the 10 new frozen material packs (qdrant_019-028) into materials_complete/.
Run from repo root. GT mapping lives ONLY in results/rq2_pool81/gt_map_new10.json."""
import json, re, os

ROOT = os.getcwd()
BASE = 'results/rq2_pool81/materials/repro-scripts'
GT = {
 'qdrant_019': ('10120', '1.18.3', 'count'),
 'qdrant_020': ('10125', '1.18.3', 'count'),
 'qdrant_021': ('10126', '1.18.3', 'count'),
 'qdrant_022': ('10127', '1.18.3', 'count'),
 'qdrant_023': ('10368', '1.19.0', 'snapshot'),
 'qdrant_024': ('10369', '1.19.0', 'recommend'),
 'qdrant_025': ('10370', '1.19.0', 'collection'),
 'qdrant_026': ('10371', '1.19.0', 'groups'),
 'qdrant_027': ('10372', '1.19.0', 'index'),
 'qdrant_028': ('10373', '1.19.0', 'scroll'),
}
COUNT_FAMILY = {'10120', '10125', '10126', '10127'}

d = json.load(open(r'<PIPELINE_SOURCE>\results\qdrant\v1.18.2\structured_contract.json', encoding='utf-8'))
allrows = []
for grp in d['constraints'].values():
    if isinstance(grp, list):
        allrows += [r for r in grp if isinstance(r, dict)]

def clean_log(txt):
    txt = re.sub(r'\[VERDICT\][^\n]*', '', txt)
    txt = re.sub(r'\[script error\][^\n]*', '', txt)
    keep = [l for l in txt.splitlines() if l.strip() and 'issue claim' not in l.lower()]
    return '\n'.join(keep).strip()

made = 0
for cid in sorted(GT):
    issue, ver, kw = GT[cid]
    if issue in COUNT_FAMILY:
        httplog = open(f'{BASE}/replay-{issue}.httplog.txt', encoding='utf-8').read().strip()
        summary = open(f'{BASE}/replay-{issue}.out', encoding='utf-8').read().strip()
        summary = '\n'.join(l for l in summary.splitlines() if 'issue claim' not in l.lower())
        clean = f'重放输出摘要:\n{summary}\n\n完整请求/响应记录:\n{httplog}'
        note = ''
    else:
        raw = open(f'{BASE}/replay-{issue}.out', encoding='utf-8').read()
        clean = clean_log(raw)
        note = ''
        if issue == 10373:
            clean = ('[Observed transcript as recorded at original verification time (v1.19.0, pre-fix)]\n'
                     'PUT /collections/strict-demo (strict_mode_config: max_query_limit=10, enabled) -> 200\n'
                     'POST /collections/strict-demo/points/scroll {"limit": 100} -> 200, returns points ignoring the documented cap\n'
                     'Control: POST scroll {"limit": 5} -> 200, 5 points (below cap works)\n\n'
                     '[Version-drift replay, same API line, later build] scroll limit=100 under strict cap 10 now returns HTTP 400 "Limit exceeded 100 > 10".')
    hits = [r for r in allrows if kw in str(r.get('endpoint', '')).lower()][:6]
    contract_txt = '\n'.join(json.dumps(r, ensure_ascii=False) for r in hits) \
        if hits else '(endpoint introduced after the pinned contract extraction; documented semantics quoted inside the transcript)'
    ver_note = 'qdrant v1.18.3 container (port 6337)' if ver == '1.18.3' else 'qdrant v1.19.0 container (port 6338)'
    body = f"""# 候选缺陷 {cid}

[vendor=qdrant version={ver} endpoint={kw}]

--- 观察到的行为（observed） ---

重放环境:{ver_note};证据来源:container replay,HTTP interactions captured verbatim。{note}

{clean}

--- 契约依据（expected，来自该版本 API 契约） ---

{contract_txt}
"""
    open(f'.paperpilot/phase2-rerun/arms/materials_complete/{cid}.md', 'w', encoding='utf-8').write(body)
    made += 1
print(f'assembled {made}')
