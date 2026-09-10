# Defect 14: int 向量 [1,2] 200 接受但读回 vector=null（接受/丢失分裂）

## Metadata
- defect_id: boundary_vector_null_empty_013
- type: Type1_IllegalSuccess
- param: vector
- novelty: NOVEL
- Endpoint: POST /objects (vector)
- Verdict: DEFECT (A=NEUTRAL→GREY_ZONE 机械 B=CONFIRMED, C=CONFIRMED, D=NO_SIGNAL)

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:8080/v1/objects" \
  -H "Content-Type: application/json" \
  -d '{"class":"BndVec","id":"...","vector":[1,2]}'
# -> HTTP 200 (accepted)；随后 GET 读回 vector=null（数据丢失）
# null / [] -> 200 (accepted)（required=false，合规）
# 对照：vector=["a","b"] -> 400
#   {"code":400,"message":"parsing body ... json: cannot unmarshal string into Go struc..."}
```

## Expected vs Actual
- Expected: 向量为 float32 array（C11yVector []float32 语义）；string 向量在 JSON 解码层 400 证明类型检查通道存在。
- Actual: int 向量 [1,2] 被 200 接受但读回 vector=null——接受与丢失分裂：客户端以为向量已存，实际静默丢弃。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: 泛锚（boundary；实际引用 structured_contract.json data_types.Object.vector array required=false + 源码 C11yVector []float32 语义）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL（版本匹配 PASS；元素类型约束属源码级而非文档级）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_logs/boundary_vector_null_empty_013.py
- Log: debate_logs/output_boundary_vector_null_empty_013.log（intvec 200 accepted + readback vector=null；strvec 400）
- 源码 文件:行号+摘录: entities/models/c11y_vector.go:28 `type C11yVector []float32`（JSON number 1 可无损进 float32，解码成功）；usecases/objects/validation/vector_validation.go:27-50 仅校验 named-vector 配置存在性与 float32 断言，无读回一致性校验。已知缺口：读回 null 的确切丢弃点未定位（可能在 vectorizer=none + legacy vector 存储路径），如实记录，仅降置信不改判。

## Impact
静默数据丢失通道：写入端成功确认、读取端向量缺失，向量检索对该对象静默失效；无告警无错误，数据质量问题难以归因。

## Novelty Gate
grade: NOVEL (no_known_hits, confidence HIGH, endorsement true)
