# Defect 7: entities/insert — Int64 列接受非数字语义的数字字符串静默强转落库（跨类型行为分裂）

## Metadata
- Defect ID: TESTVDB-MILVUS-7
- defect_id (script): vein_insert_type_coercion_2
- Type: Type2_PoorDiagnostics（类型恒真）
- Endpoint: POST /v2/vectordb/entities/insert
- Param: data[].val（param_name: data）
- Novelty: NOVEL（gate, no_known_hits, confidence HIGH）

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:19530/v2/vectordb/entities/insert" \
  -H "Content-Type: application/json" \
  -d '{"collectionName":"<Int64 列 val 的集合>","data":[{"id":3,"val":"5"}]}'
```

## Expected vs Actual
- Expected: Int64 列传字符串 "5" 应报类型错误（schema 类型匹配，milvus_type_entities_insert_001 'wrong type -> ErrInvalidInsertData'）
- Actual: `PASS int64_string_accepted {'code':0,'cost':0,'data':{'insertCount':1,'insertIds':[3]}}`；读回 `{'id':3,'score':1,'val':5,...}`——val 已变 int 5，静默强转落库
- 对照：`control_float_bool_rejected code:1804 'unable to cast "true" of type string to float32'`；`int64_bool_rejected_control code:1804 'strconv.ParseInt: parsing "true": invalid syntax'`

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: vein_insert_type_coercion（vein 自生契约；相邻官方约束 milvus_type_entities_insert_001）
  - assertion: `insert 标量字段值必须符合 schema 声明类型；字符串 "5" 传入 Int64 列应报类型错误，不得静默强转`；api_violates_assertion=true
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL（官方约束未显式约束标量字符串强转——一致性 PARTIAL，如实记）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: vein_scripts/vein_insert_type_coercion_2.py（四路对照：合法/str-int/str-bool/float-bool；grade B）
- Log: vein_scripts/output_vein_insert_type_coercion_2.log

### 源码 文件:行号+摘录
- internal/distributed/proxy/httpserver/utils.go checkAndSetData L287-630：
  - L417-421 Bool 分支 `cast.ToBoolE(dataString)` → 失败报错
  - L438-443 Int64 分支 `json.Number(dataString).Int64()` → "5"→5 解析成功；非数字报 1804
  - L565-575 Float 分支 `cast.ToFloat32E`
- 根因：三分支转换器不同（json.Number vs cast.*），数字字符串恰在 Int64 分支可解析——同 string 输入 bool/float 拒、int 收，无注释说明设计意图（surviving=不对称性本身）

## Impact
同一列同类输入（string）行为分裂：数字字符串静默强转 int 落库（读回类型改变），非数字字符串 1804 拒。数据完整性受损——客户端类型错误被无声吞掉，库内出现客户端从未发送的类型；跨版本/SDK 迁移时读回类型与写入类型不一致。
