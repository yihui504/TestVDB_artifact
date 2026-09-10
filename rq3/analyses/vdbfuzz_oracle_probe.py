import requests
B = "http://127.0.0.1:6340"
def oracle(resp, exc=None):
    """VDBFuzz 的 connectivity_check_func 语义 (vdbfuzz/mutator.py:511): status_code < 500"""
    if exc is not None:
        return False
    return resp.status_code < 500

r1 = requests.put(f"{B}/collections/normal", json={"vectors": {"size": 100, "distance": "Cosine"}}, timeout=15)
print(f"[1] normal create     -> HTTP {r1.status_code}  oracle_fires={not oracle(r1)}")

r2 = requests.put(f"{B}/collections/inj2", json={"vectors": {"size": 2**63, "distance": "Cosine"}}, timeout=30)
print(f"[2] size=2**63 create -> HTTP {r2.status_code}  oracle_fires={not oracle(r2)}   <-- 500 => oracle 记录 failure")

r3 = requests.get(f"{B}/collections", timeout=15)
print(f"[3] server still up   -> HTTP {r3.status_code}  (服务未死 => oracle 是 5xx 检测器, 不是服务死亡检测器)")
