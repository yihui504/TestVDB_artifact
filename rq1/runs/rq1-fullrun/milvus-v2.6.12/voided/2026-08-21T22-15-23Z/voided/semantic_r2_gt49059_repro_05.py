"""GT #49059 精确复刻：COSINE IVF_FLAT nlist=128, dim=128, 10000 normalized 向量自查询。
判定：distance > 1.0 即 GT 主张的浮点溢出（segcore 无 clamp）。"""
import json, math, os, random, urllib.request

BASE = os.environ.get("TESTVDB_DB_URL", "http://localhost:19530")
def req(path, body):
    r = urllib.request.Request(BASE + path, json.dumps(body).encode(),
        {"Authorization": "Bearer root:Milvus", "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=60).read())

COL = "gt49059_repro"
req("/v2/vectordb/collections/drop", {"collectionName": COL})
random.seed(42)
vecs = []
for i in range(10000):
    v = [random.random() for _ in range(128)]
    n = math.sqrt(sum(x*x for x in v))
    vecs.append([round(x/n, 9) for x in v])
    if (i+1) % 200 == 0: n = math.sqrt(sum(x*x for x in v))  # placeholder no-op
# 严格归一化（二次归一化提高精度）
vecs = []
random.seed(42)
for i in range(10000):
    v = [random.random() for _ in range(128)]
    n2 = math.sqrt(sum(x*x for x in v)); v = [x/n2 for x in v]
    n3 = math.sqrt(sum(x*x for x in v)); v = [x/n3 for x in v]
    vecs.append(v)

print(req("/v2/vectordb/collections/create", {"collectionName": COL, "dimension": 128, "metricType": "COSINE", "indexType": "IVF_FLAT", "params": {"nlist": 128}})["code"], "create")
# 分批 insert
for b in range(10):
    batch = [{"id": i, "vector": vecs[i]} for i in range(b*1000, (b+1)*1000)]
    r = req("/v2/vectordb/entities/insert", {"collectionName": COL, "data": batch})
    assert r["code"] == 0, r
print("inserted 10000")
req("/v2/vectordb/collections/load", {"collectionName": COL})
import time; time.sleep(3)
# 自查询 100 个（分 10 批）
over = 0; worst = 0.0; dists = []
for b in range(10):
    q = [vecs[i] for i in range(b*10, (b+1)*10)]
    r = req("/v2/vectordb/entities/search", {"collectionName": COL, "data": q,
        "limit": 1, "outputFields": []})
    assert r["code"] == 0, r
    for hit in r["data"]:
        d = hit.get("distance")
        dists.append(d)
        if d is not None:
            worst = max(worst, d)
            if d > 1.0: over += 1
print(f"identical self-search 100: over_1.0={over}, worst={worst!r}, sample={dists[:5]}")
req("/v2/vectordb/collections/drop", {"collectionName": COL})
print(f"VERDICT: {'DEFECT_FOUND' if over > 0 else 'NO_DEFECT'}{'' if over == 0 else ' (COSINE distance > 1.0 for identical)'}")
