# -*- coding: utf-8 -*-
"""Run an issue replay script with full HTTP request/response capture.
Usage: python runner_with_capture.py replay-10120.py out.httplog.txt
Captures every urllib call (method, url, payload, status, body) into out file."""
import sys, io, urllib.request, urllib.error

target, out_path = sys.argv[1], sys.argv[2]
lines = []
_orig = urllib.request.urlopen

class _FakeResp:
    def __init__(self, status, txt, headers):
        self.status = status
        self.code = status
        self._txt = txt
        self.headers = headers
    def read(self):
        return self._txt.encode()
    def getcode(self):
        return self.status
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False

def rec_urlopen(r, timeout=30, **kw):
    body = r.data.decode('utf-8', 'replace') if r.data else None
    try:
        resp = _orig(r, timeout=timeout, **kw)
        txt = resp.read().decode('utf-8', 'replace')
        lines.append(f"=== REQ {r.get_method()} {r.full_url} ===\npayload: {body}\n=== RESP ===\nstatus: {resp.status}\nbody: {txt[:800]}")
        return _FakeResp(resp.status, txt, resp.headers)
    except urllib.error.HTTPError as e:
        txt = e.read().decode('utf-8', 'replace')
        lines.append(f"=== REQ {r.get_method()} {r.full_url} ===\npayload: {body}\n=== RESP ===\nstatus: {e.code}\nbody: {txt[:800]}")
        raise

urllib.request.urlopen = rec_urlopen
src = open(target, encoding='utf-8').read()
g = {'__name__': '__main__'}
try:
    exec(compile(src, target, 'exec'), g)
    rc = 0
except SystemExit as e:
    rc = e.code or 0
except Exception as e:
    lines.append(f"[script error] {type(e).__name__}: {e}")
    rc = 1
open(out_path, 'w', encoding='utf-8').write('\n'.join(lines))
sys.exit(rc)
