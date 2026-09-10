# Defect 16: batch 通道三态分裂——committed 20 vs reported 21，COUNT 不计入，未建类报 SUCCESS

## Metadata
- defect_id: state_batch_04
- type: Type4_StateLogicViolation
- param: objects
- novelty: NOVEL
- Endpoint: POST /batch/objects
- Verdict: DEFECT (A=NEUTRAL→GREY_ZONE LLM 兜底 B=CONFIRMED, C=CONFIRMED, D=NO_SIGNAL)

## Reproduction (curl)
```bash
# 25 项 batch：21 合法 + 4 非法 int（"not-an-int-1" 等）+ 混入未创建类 NoSuchClassX 的对象
curl -s -X POST "http://localhost:8080/v1/batch/objects" \
  -H "Content-Type: application/json" \
  -d '{"objects":[{"class":"StBatD","properties":{"num":"not-an-int-1"}}, ..., {"class":"NoSuchClassX", ...}]}'
# -> HTTP 200；batch reported: total=25 success=21 errors=4
# 异常 1：committed count=20 ≠ reported success=21（计数分裂）
# 异常 2：ghost-check class=NoSuchClassX read=200 in_schema=True
#         （未创建类被静默 auto-create，该项报 SUCCESS）
# 异常 3：Aggregate COUNT 通道不计入该对象
```

## Expected vs Actual
- Expected: 状态不变式——插 N 对象 COUNT 返 N（weaviate_state_object_count_001）；写通道、schema 通道、计数通道三者一致。
- Actual: 三通道互相矛盾——batch 报 success=21 但实际 committed=20；未创建类的对象报 SUCCESS 且类被静默建出，但 COUNT 查询不计入该对象。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: 泛锚（batch_partial_commit_consistency；实际引用 weaviate_state_collection_creation_001 'Collection exists in GET /schema response after POST /schema' + weaviate_state_object_count_001 'COUNT query returns N after inserting N objects'）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL（版本匹配 PASS；openapi batch/objects 部分失败逐项报告语义）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_logs/state_batch_04.py
- Log: debate_logs/output_state_batch_04.log（ghost-check read=200 in_schema=True；committed=20 vs reported 21）
- 源码 文件:行号+摘录: usecases/config/environment.go:851-854 autoSchema 默认开启（AUTOSCHEMA_ENABLED 未设即 true）——auto-schema 建类本身 by-design；surviving 缺陷：(1) 该项报 SUCCESS 而 Aggregate COUNT 不计入（落盘则计数不一致是缺陷，未落盘则 SUCCESS 是谎报）；(2) batch_add.go:197 `autoSchemaManager.autoSchema(ctx, principal, true, fetchedClasses, obj)`（allowCreateClass=true）与单条通道行为分裂；(3) committed/reported 计数差 1 无解释。

## Impact
客户端依据 batch 响应的 success 计数做提交确认会高估持久化对象数；COUNT 聚合与实际数据不一致破坏监控与容量规划的正确性；auto-create 的幽灵类污染 schema。

## Novelty Gate
grade: NOVEL (no_known_hits, confidence HIGH, endorsement true; precision LOW)
