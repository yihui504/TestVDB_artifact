# Defect 12: DELETE /batch/objects 停用词 filter → REST 500，GraphQL 同输入 200+结构化 errors

## Metadata
- Defect ID: TESTVDB-WEAVIATE-12
- defect_id: vein_batchdelete_stopword_500_02
- Type: Type3_RuntimeFailure
- Severity: High（Type3 推断）
- Param: match.where.valueText
- Endpoint: DELETE /v1/batch/objects
- Novelty: NOVEL
- Discovered: 2026-08-21T17-17-51Z session

## Reproduction (curl)
```bash
curl -s -X DELETE "http://localhost:8080/v1/batch/objects" -H "Content-Type: application/json" \
  -d '{"match":{"class":"C","where":{"operator":"Equal","path":["name"],"valueText":"the"}}}'
# → HTTP 500 {"error":[{"message":"batch delete objects: cannot find objects: find matching doc ids in shard \"l1HZo8cATnEq\": docIds: invalid search term, only stopwords pr..."}}}
# control 非停用词: 200；control GraphQL 同 filter: 200 + 结构化 errors（stopword-err-present: True）
```

## Expected vs Actual
- Expected: filter 值全停用词属 caller-input 错误（请求侧可判定），应结构化 4xx/错误负载而非 5xx——GraphQL 通道已证明该错误可结构化处理。
- Actual: REST batch delete → HTTP 500（server fault 信号）；GraphQL 同输入 → 200 + errors 字段。同一输入错误跨 API 面分类不一致。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: vein_stopword_error_channel（vein 探索性约束，非结构化契约内置；断言有行为对照支撑，机械B HTTP语义恒真 CONFIRMED）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL — 错误源 ErrOnlyStopwords 文案本身面向 caller（"Stopwords can be configured in class.invertedIndexConfig.stopwords"）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: vein_scripts/vein_batchdelete_stopword_500_02.py
- Log: debate_logs/output_vein_batchdelete_stopword_500_02.log（log_pattern: "batch delete stopword: 500 ...only stopwords pr"，grade A，多脚本稳定触发）
- 源码 adapters/repos/db/inverted/searcher.go L110-111：
  ```go
  var ErrOnlyStopwords = fmt.Errorf("invalid search term, only stopwords provided. " +
    "Stopwords can be configured in class.invertedIndexConfig.stopwords")
  ```
  传播链：searcher → db/batch.go L197-199 errors.Wrapf("cannot find objects") → batch_delete.go L99 fmt.Errorf("batch delete objects: %w")（未包 ErrInvalidUserInput）→ handler default → 500；GraphQL 面在 resolver 层把同一错误转为 errors 字段（200）。

## Impact
常见用户输入（"the" 等停用词作 filter 值）触发 5xx；跨 API 面（REST/GraphQL）行为分裂使错误契约不一致；500 触发重试与误告警。
