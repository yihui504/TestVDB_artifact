"""Weaviate attack runtime — 应急实现（v1.37.4 session）。

规范（agents/_target_api_reference.md 强制 runtime 协议 v2.4）引用了
`from runtime import get_runtime`，但 runtime.py 从未随插件落盘——机制缺失件。
本文件按规范语义实现 weaviate 分支，放在 debate_logs/ 供同目录脚本 import
（Python sys.path 含脚本所在目录）。

判定语义（规范三态）：
- persist（回读值 == 攻击值）→ DEFECT_FOUND（真 Type1）
- silent-drop（回读无该字段）→ NO_DEFECT
- silent-normalize（回读值 != 攻击值但请求被接受）→ DEFECT_FOUND（Type2 信号）
- 请求被拒（4xx）→ NO_DEFECT（validation works）
"""
import json
import os

import requests

BASE_URL = os.environ.get("TESTVDB_DB_URL", "http://localhost:8080").rstrip("/")

PATHS = {
    "create_schema": ("POST", "/v1/schema"),
    "list_schema": ("GET", "/v1/schema"),
    "describe_schema": ("GET", "/v1/schema/{name}"),
    "drop_schema": ("DELETE", "/v1/schema/{name}"),
    "add_property": ("POST", "/v1/schema/{name}/properties"),
    "create_object": ("POST", "/v1/objects"),
    "batch_objects": ("POST", "/v1/batch/objects"),
    "get_object": ("GET", "/v1/objects/{id}"),
    "delete_object": ("DELETE", "/v1/objects/{id}"),
    "graphql": ("POST", "/v1/graphql"),
}


class WeaviateRuntime:
    PATHS = PATHS

    def request(self, method, path_key, body=None, path_params=None):
        """三元组契约 (status, body_dict_or_None, raw_text)——同 safe_request 规范。"""
        method_key, tmpl = PATHS[path_key]
        path = tmpl.format(**(path_params or {}))
        url = f"{BASE_URL}{path}"
        try:
            if method.upper() in ("GET", "DELETE"):
                r = requests.request(method.upper(), url, timeout=30)
            elif isinstance(body, str):
                # 已是 JSON 文本（如 graphql query 字符串）→ 原样发，避免 json= 双重编码
                r = requests.request(method.upper(), url, data=body.encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, timeout=30)
            else:
                r = requests.request(method.upper(), url, json=body or {}, timeout=30)
            try:
                body_obj = json.loads(r.text)
            except json.JSONDecodeError:
                body_obj = None
            return r.status_code, body_obj, r.text
        except Exception as e:  # noqa: BLE001 — 网络失败归为脚本错误，status 0
            return 0, None, str(e)

    def _describe(self, class_name):
        status, body, _raw = self.request("GET", "describe_schema", path_params={"name": class_name})
        if status != 200:
            return None
        return body

    @staticmethod
    def _dig(obj, path):
        """按 path list 取字段值；字段缺失返回 _MISSING。"""
        cur = obj
        for p in path:
            if isinstance(cur, dict) and p in cur:
                cur = cur[p]
            else:
                return _MISSING
        return cur

    def judge_schema_attack(self, status, raw, class_name, attack_path, attack_value,
                            setup_ok=True):
        if not setup_ok:
            return "SCRIPT_ERROR"
        if status >= 400:
            return "NO_DEFECT"  # 请求被拒：validation works
        # 请求被接受 → 回读三态判定
        body = self._describe(class_name)
        if body is None:
            return "SCRIPT_ERROR"
        actual = self._dig(body, attack_path)
        if actual is _MISSING:
            return "NO_DEFECT"  # silent-drop：字段被丢（设计行为）
        if actual == attack_value:
            return "DEFECT_FOUND"  # persist：非法值被持久化
        # silent-normalize：值被改写（Type2 信号）
        print(f"[judge] silent-normalize: {attack_path[-1]} {attack_value!r} -> {actual!r}")
        return "DEFECT_FOUND"

    def setup_default(self, class_name, dim=128, metric="cosine"):
        payload = {
            "class": class_name,
            "vectorizer": "none",
            "vectorIndexType": "hnsw",
            "vectorIndexConfig": {"distance": metric, "vectorCacheMaxObjects": 500000},
            "properties": [{"name": "text", "dataType": ["text"]}],
        }
        status, raw = self.request("POST", "create_schema", payload)
        return status < 400, raw


class _Missing:
    def __repr__(self):
        return "<MISSING>"


_MISSING = _Missing()


def get_runtime():
    """按 TESTVDB_TARGET 分发；本 session 仅 weaviate。"""
    target = os.environ.get("TESTVDB_TARGET", "weaviate")
    if target == "weaviate":
        return WeaviateRuntime()
    raise NotImplementedError(f"runtime for {target} not implemented in this session stub")
