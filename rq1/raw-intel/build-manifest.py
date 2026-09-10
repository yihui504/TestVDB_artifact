#!/usr/bin/env python3
"""构建 Phase 2 candidate manifest: raw json(body) + CSV(GT category) 对齐 + 版本提取."""
import json, csv, re

RAW_DIR = r'<ARTIFACT_ROOT>\.paperpilot\phase1-raw'
CSV = r'<DESKTOP>\pipelinehost\data\vdbms-issues.csv'
OUT = RAW_DIR + r'\manifest.json'

REPOS = ['milvus-io/milvus', 'qdrant/qdrant', 'weaviate/weaviate']

# 版本提取正则(按 vendor)
VERSION_RE = {
    'milvus-io/milvus': [
        r'(?i)milvus\s+version[:\s]*v?(\d+\.\d+(?:\.\d+)?)',
        r'(?i)milvusdb/milvus:v?(\d+\.\d+(?:\.\d+)?)',
        r'(?i)(?<![a-z])milvus\s+v?(\d+\.\d+(?:\.\d+)?)',  # "milvus v2.5.26" 空格格式
    ],
    'qdrant/qdrant': [
        r'(?i)qdrant\s+version[:\s]*v?(\d+\.\d+(?:\.\d+)?)',
        r'(?i)qdrant/qdrant:v?(\d+\.\d+(?:\.\d+)?)',
        r'(?i)QDRANT_VERSION[=\s]*v?(\d+\.\d+(?:\.\d+)?)',
        r'(?i)(?<![a-z])qdrant\s+v?(\d+\.\d+(?:\.\d+)?)',  # "qdrant v1.18.1" 空格格式
    ],
    'weaviate/weaviate': [
        r'(?i)(?:semitechnologies/)?weaviate:v?(\d+\.\d+(?:\.\d+)?)',
        r'(?i)weaviate\s+version[:\s]*v?(\d+\.\d+(?:\.\d+)?)',
        r'(?i)(?<![a-z])weaviate\s+v?(\d+\.\d+(?:\.\d+)?)',  # "Clean weaviate v1.38.2 container"
    ],
}


def extract_version(repo, body):
    for pat in VERSION_RE[repo]:
        m = re.search(pat, body or '')
        if m:
            return m.group(1), pat
    return None, None


# 1. raw json
raw = {}
for repo in REPOS:
    fn = RAW_DIR + '\\' + repo.replace('/', '-') + '.json'
    for it in json.load(open(fn, encoding='utf-8')):
        key = (repo, it['number'])
        raw[key] = {
            'repo': repo, 'number': it['number'],
            'title': it['title'], 'body': it.get('body') or '',
            'state': it['state'], 'state_reason': it.get('state_reason'),
            'created_at': it['created_at'],
            'is_pr': 'pull_request' in it and it['pull_request'] is not None,
        }
print(f'raw json entries: {len(raw)}')

# 2. CSV GT 对齐
gt = {}
rows = list(csv.reader(open(CSV, encoding='utf-8')))
for r in rows[1:]:
    if len(r) < 5:
        continue
    gt[(r[0], int(r[1]))] = r[4]  # (repo, number) -> category
print(f'csv data rows: {len(rows) - 1}, gt keys: {len(gt)}')

# 对齐差异
raw_only = set(raw) - set(gt)
csv_only = set(gt) - set(raw)
if raw_only:
    print('WARN raw-only (no GT):', sorted(raw_only))
if csv_only:
    print('WARN csv-only (no raw):', sorted(csv_only))

# 3. 版本提取
manifest, missing = [], []
for key, it in sorted(raw.items()):
    ver, src = extract_version(it['repo'], it['body'])
    item = dict(it)
    item['gt_category'] = gt.get(key, 'UNKNOWN')
    item['reported_version'] = ver
    item['version_source'] = src
    manifest.append(item)
    if not ver:
        missing.append((key[0], key[1], it['created_at'][:10]))

# 3b. releases API 反查缺失版本(created_at 之前的最新 release)
def wait_for_limit(need_n):
    import urllib.request, time
    while True:
        d = json.load(urllib.request.urlopen(urllib.request.Request(
            'https://api.github.com/rate_limit', headers={'User-Agent': 'testvdb'})))
        rem = d['resources']['core']['remaining']
        if rem >= need_n + 2:
            return rem
        wait = d['resources']['core']['reset'] - time.time() + 5
        print(f'  [rate limit] remaining={rem}, sleep {wait:.0f}s', flush=True)
        time.sleep(wait)


def fetch_releases(repo):
    import urllib.request, time
    url = f'https://api.github.com/repos/{repo}/releases?per_page=50'
    req = urllib.request.Request(url, headers={'User-Agent': 'testvdb'})
    d = json.load(urllib.request.urlopen(req))
    time.sleep(0.5)
    # 过滤 client SDK tag(如 client/v2.6.5)和预发布
    rels = [(r['tag_name'], r['published_at']) for r in d
            if not r['tag_name'].startswith('client/') and not r['prerelease']]
    return rels

need = [(m['repo'], m['number'], m['created_at']) for m in manifest if not m['reported_version']]
if need:
    print(f'\n[releases lookup] {len(need)} entries missing version')
    cache = {}
    for repo, num, created in need:
        if repo not in cache:
            wait_for_limit(len({r for r, _, _ in need}))
            cache[repo] = fetch_releases(repo)
        best = None
        for tag, pub in cache[repo]:
            m = re.search(r'(\d+\.\d+(?:\.\d+)?)', tag)
            if not m:
                continue
            if pub <= created and (best is None or pub > best[1]):
                best = (m.group(1), pub)
        if best:
            for item in manifest:
                if item['repo'] == repo and item['number'] == num:
                    item['reported_version'] = best[0]
                    item['version_source'] = 'releases-api (latest <= created_at)'
            print(f'  {repo}#{num} {created[:10]} -> v{best[0]} ({best[1][:10]})')
        else:
            print(f'  {repo}#{num} {created[:10]} -> STILL MISSING')

# 4. 输出
json.dump(manifest, open(OUT, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
print(f'\nmanifest: {len(manifest)} entries -> {OUT}')

# 5. 汇总
print('\n== version extraction summary ==')
for repo in REPOS:
    items = [m for m in manifest if m['repo'] == repo]
    have = [m for m in items if m['reported_version']]
    vers = {}
    for m in have:
        vers.setdefault(m['reported_version'], 0)
        vers[m['reported_version']] += 1
    print(f'{repo}: {len(have)}/{len(items)} with version')
    for v, c in sorted(vers.items()):
        print(f'    v{v}: {c}')

print('\n== missing version (created_at) ==')
for repo, num, dt in missing:
    print(f'  {repo}#{num}  {dt}')

print('\n== GT category distribution ==')
cats = {}
for m in manifest:
    cats[m['gt_category']] = cats.get(m['gt_category'], 0) + 1
for c, n in sorted(cats.items(), key=lambda x: -x[1]):
    print(f'  {c}: {n}')
