# 候选缺陷 defect-2

[vendor=qdrant endpoint=unknown]

--- 观察到的行为（observed） ---

- LEG whitespace-only: expected=4xx-family actual=200 body[:200]='{"result":{"aliases":[]},"status":"ok","time":0.000014622}'
- [rest, same script] LEG numeric-literal: expected=4xx-family actual=200 body[:200]='{"result":{"aliases":[]},"status":"ok","time":6.652e-6}' -> DISPOSITION: defect:Type1_IllegalSuccess
- [rest, same script] LEG boolean-literal: expected=4xx-family actual=200 body[:200]='{"result":{"aliases":[]},"status":"ok","time":5.107e-6}' -> DISPOSITION: defect:Type1_IllegalSuccess
- [rest, same script] LEG null-literal: expected=4xx-family actual=200 body[:200]='{"result":{"aliases":[]},"status":"ok","time":4.353e-6}' -> DISPOSITION: defect:Type1_IllegalSuccess
- [rest, same script] LEG embedded-space: expected=4xx-family actual=200 body[:200]='{"result":{"aliases":[]},"status":"ok","time":5.365e-6}' -> DISPOSITION: defect:Type1_IllegalSuccess
- [rest, same script] LEG dot-segment: expected=4xx-family actual=200 body[:200]='{"result":{"aliases":[]},"status":"ok","time":0.000016142}' -> DISPOSITION: defect:Type1_IllegalSuccess — AMBIGUOUS FACE: runtime substitutes path params by raw str.format (scripts/runtime/qdrant.py:80) with no percent-encoding, so /collections/../aliases was sent; server wraps NormalizePath (src/actix/mod.rs:121), so this 200 came either from the /aliases all-listing route after dot-segment normalization or from the aliases route accepting '..' (dots are not in the legacy forbidden set ['/', '\0']); both paths yield the identical 200-empty body
- [rest, same script] LEG empty-string: expected=4xx-family actual=404 body[:200]='{"status":{"error":"Not found: Collection `aliases` doesn't exist!"},"time":6.737e-6}' -> DISPOSITION: clean (404) — ROUTING ARTIFACT: the error text names Collection `aliases`, i.e. the request was served by the collection-info route with collection_name='aliases' after the empty path segment collapsed; the aliases route's own validator was never reached

--- 契约（expected，来自该版本文档/契约） ---

assertion: 200 list of {alias_name, collection_name}; 404 unknown collection
source_url: 
doc_version: 
