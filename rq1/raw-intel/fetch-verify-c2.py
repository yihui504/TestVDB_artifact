#!/usr/bin/env python3
"""抓取剩余 24 个 TP_FIXED 的 comments，验证真实关闭原因。

输出: verify-c2/{repo}-{number}.json + 控制台精简证据（非 <submitter> 的评论）
"""
import urllib.request, json, time, os

ISSUES = [
    ("milvus-io/milvus", 47635), ("milvus-io/milvus", 47636),
    ("milvus-io/milvus", 47755), ("milvus-io/milvus", 47763),
    ("milvus-io/milvus", 47766), ("milvus-io/milvus", 49059),
    ("milvus-io/milvus", 49844), ("milvus-io/milvus", 49890),
    ("milvus-io/milvus", 50018), ("milvus-io/milvus", 50324),
    ("milvus-io/milvus", 51084), ("milvus-io/milvus", 51085),
    ("qdrant/qdrant", 9039), ("qdrant/qdrant", 9149),
    ("qdrant/qdrant", 9255), ("qdrant/qdrant", 9373),
    ("qdrant/qdrant", 9416), ("qdrant/qdrant", 9417),
    ("qdrant/qdrant", 9418), ("qdrant/qdrant", 9419),
    ("qdrant/qdrant", 9420),
    ("weaviate/weaviate", 11729), ("weaviate/weaviate", 11981),
    ("weaviate/weaviate", 12041),
]

OUT = r'<ARTIFACT_ROOT>\.paperpilot\phase1-raw\verify-c2'
os.makedirs(OUT, exist_ok=True)


def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'testvdb'})
    return json.load(urllib.request.urlopen(req))


for repo, num in ISSUES:
    url = f'https://api.github.com/repos/{repo}/issues/{num}/comments?per_page=100'
    try:
        cs = get(url)
    except Exception as e:
        print(f'FAIL {repo}#{num}: {e}')
        continue
    fn = os.path.join(OUT, f'{repo.replace("/", "-")}-{num}.json')
    json.dump(cs, open(fn, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
    keep = []
    for c in cs:
        u = c['user']['login']
        if u == '<submitter>':
            continue
        body = c['body'].replace('\n', ' ')[:250]
        keep.append(f'{u}: {body}')
    print(f'===== {repo}#{num} ({len(cs)} comments, {len(keep)} non-author)')
    for k in keep:
        print('  ', k)
    time.sleep(1.0)
