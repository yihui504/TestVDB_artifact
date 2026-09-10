#!/usr/bin/env python3
"""为 17 个人工确认的 TP_FIXED_PR 抓 timeline, 提取关联 PR 编号。

rate limit 不足时自动等待到 reset。输出存 verify-c3/, 控制台打印 PR 证据。
"""
import urllib.request, json, time, os

ISSUES = [
    ("milvus-io/milvus", 50355), ("milvus-io/milvus", 52309),
    ("milvus-io/milvus", 52311), ("milvus-io/milvus", 52313),
    ("milvus-io/milvus", 52315), ("milvus-io/milvus", 52325),
    ("milvus-io/milvus", 52307), ("milvus-io/milvus", 49843),
    ("qdrant/qdrant", 9421), ("qdrant/qdrant", 9522),
    ("qdrant/qdrant", 10120),
    ("weaviate/weaviate", 11399), ("weaviate/weaviate", 11400),
    ("weaviate/weaviate", 11401), ("weaviate/weaviate", 11730),
    ("weaviate/weaviate", 11732), ("weaviate/weaviate", 11741),
]

OUT = r'<ARTIFACT_ROOT>\.paperpilot\phase1-raw\verify-c3'
os.makedirs(OUT, exist_ok=True)
HDRS = {'User-Agent': 'testvdb',
        'Accept': 'application/vnd.github.mockingbird-preview+json'}


def get(url):
    req = urllib.request.Request(url, headers=HDRS)
    return json.load(urllib.request.urlopen(req))


def wait_for_limit():
    while True:
        d = get('https://api.github.com/rate_limit')
        rem = d['resources']['core']['remaining']
        if rem >= 2:
            return rem
        wait = d['resources']['core']['reset'] - time.time() + 5
        print(f'  [rate limit] remaining={rem}, sleep {wait:.0f}s', flush=True)
        time.sleep(wait)


for repo, num in ISSUES:
    wait_for_limit()
    url = f'https://api.github.com/repos/{repo}/issues/{num}/timeline?per_page=100'
    try:
        evs = get(url)
    except Exception as e:
        print(f'FAIL {repo}#{num}: {e}', flush=True)
        continue
    fn = os.path.join(OUT, f'{repo.replace("/", "-")}-{num}.json')
    json.dump(evs, open(fn, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
    prs = []
    for e in evs:
        src = e.get('source', {}).get('issue', {})
        if e['event'] == 'cross-referenced' and src.get('pull_request') is not None:
            prs.append((src.get('number'), src.get('title', '')[:70]))
    print(f'{repo}#{num}: PRs -> {prs}', flush=True)
    time.sleep(1.0)
