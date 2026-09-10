#!/usr/bin/env python3
"""分析 126 条 candidate 的 probe 可自动提取程度: curl 块、缺陷类型关键词、API 端点."""
import json, re

MANIFEST = r'<ARTIFACT_ROOT>\.paperpilot\phase1-raw\manifest.json'
manifest = json.load(open(MANIFEST, encoding='utf-8'))

# 缺陷类型关键词 -> 粗分类
TYPE_HINTS = [
    ('crash', r'(?i)\b(crash|panic|segfault|OOM|500 error|internal error)\b'),
    ('param_validation', r'(?i)\b(accepts?|rejects?|validation|invalid|negative|zero|overflow|out.of.range|missing)\b'),
    ('type_coercion', r'(?i)\b(coerc|string number|numeric string|type validation|wrong.type|silently)\b'),
    ('semantics', r'(?i)\b(wrong|incorrect|under.?count|over.?count|inconsistent|mismatch|unexpected)\b'),
    ('doc_mismatch', r'(?i)\b(documentation|undocumented|spec|OpenAPI)\b'),
]

def curl_blocks(body):
    """提取 bash 块中的 curl 命令."""
    blocks = re.findall(r'```(?:bash|sh|shell)\s*\n(.*?)```', body or '', re.S)
    curls = []
    for b in blocks:
        for line in b.split('\n'):
            line = line.strip()
            if line.startswith('curl'):
                curls.append(line)
    return curls

def api_endpoints(body, repo):
    """提取 API 端点引用."""
    pats = {
        'milvus-io/milvus': [r'(?:POST|GET|PUT|DELETE|PATCH)\s+/(v2/vectordb/[\w/{}-]+)', r'`?(?:POST|GET)\s+/(v2/[\w/{}-]+)'],
        'qdrant/qdrant': [r'(?:POST|GET|PUT|DELETE|PATCH)\s+/(collections|points|snapshots|cluster)[\w/{}-]*'],
        'weaviate/weaviate': [r'(?:POST|GET|PUT|DELETE|PATCH)\s+/(v1/[\w/{}-]+)'],
    }
    eps = set()
    for p in pats.get(repo, []):
        eps |= set(re.findall(p, body or '', re.I))
    return sorted(eps)

stats = {'curl': 0, 'no_curl': 0}
types = {}
by_repo = {}
endpoint_rows = []
for it in manifest:
    repo = it['repo']
    body = it['body']
    curls = curl_blocks(body)
    eps = api_endpoints(body, repo)
    key = 'curl' if curls else 'no_curl'
    stats[key] += 1
    by_repo.setdefault(repo, {}).setdefault(key, 0)
    by_repo[repo][key] += 1

    # 缺陷类型(取 title 关键词)
    matched = []
    for tname, pat in TYPE_HINTS:
        if re.search(pat, it['title']):
            matched.append(tname)
    if not matched:
        matched = ['unknown']
    for t in matched:
        types[t] = types.get(t, 0) + 1

    if not curls:
        endpoint_rows.append((repo, it['number'], it['gt_category'], ','.join(eps)[:60] or '-', it['title'][:80]))

print('== curl 块覆盖率 ==')
for repo, d in sorted(by_repo.items()):
    print(f'  {repo}: curl={d.get("curl", 0)} no_curl={d.get("no_curl", 0)}')
print(f'  total: curl={stats["curl"]} no_curl={stats["no_curl"]}')

print('\n== 缺陷类型分布(按 title 关键词, 一条可多类) ==')
for t, n in sorted(types.items(), key=lambda x: -x[1]):
    print(f'  {t}: {n}')

print(f'\n== no_curl 条目({len(endpoint_rows)}) ==')
for repo, num, gt, eps, title in endpoint_rows:
    print(f'  {repo.split("/")[1]}#{num} [{gt}] eps={eps} | {title}')
