import sys, json, urllib.request, urllib.error
BASE = "http://localhost:19530"
HDR = {"Authorization": "Bearer root:Milvus", "Content-Type": "application/json"}

def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers=HDR)
    try:
        r = urllib.request.urlopen(req, timeout=15)
        return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read().decode())
        except Exception: return e.code, {}
    except Exception as e:
        return -1, {"err": str(e)}

if __name__ == "__main__":
    path, body = sys.argv[1], sys.argv[2]
    s, d = post(path, json.loads(body))
    print(s, json.dumps(d)[:400])
