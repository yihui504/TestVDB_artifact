# Defect 2: desiredCount=100000 无上限校验致容器挂起（DoS 面，Type3）

## Metadata
- defect_id: boundary_sharding_desiredCount_dos_002
- type: Type3_RuntimeFailure
- param: shardingConfig.desiredCount
- novelty: NOVEL
- Endpoint: POST /v1/schema
- Verdict: DEFECT (A/B/C=CONFIRMED, D=NO_SIGNAL)

## Reproduction (curl)
```bash
curl -s -m 30 -X POST "http://localhost:8080/v1/schema" \
  -H "Content-Type: application/json" \
  -d '{"class":"BndShardDos","vectorizer":"none","shardingConfig":{"desiredCount":100000}}'
# -> 连接失败：HTTPConnectionPool ... Max retries exceeded（容器挂起，4.1s）
# 同族观测：desiredCount=2147483647 -> Read timed out (timeout=30)
#          desiredCount=1000000000000 -> RemoteDisconnected（容器被打挂）
```

## Expected vs Actual
- Expected: 无 sanity cap 的天文数字分片数应在请求侧被拒绝（4xx），或至少不拖垮服务。
- Actual: 无上限校验，大值直接进入分片创建流程，容器挂起/连接中断，服务不可用。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: weaviate_range_sharding_desired_count_001（>=1，且无上限 sanity check）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL（go-func 引用，同 001；源码核对一致）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_logs/boundary_sharding_desiredCount_dos_002.py
- Log: debate_logs/output_boundary_sharding_desiredCount_dos_002.log（VERDICT: DEFECT_FOUND Type3_RuntimeFailure）
- 源码 文件:行号+摘录: usecases/sharding/config/config.go L42 `c.DesiredVirtualCount = c.DesiredCount * c.VirtualPerPhysical`（大值乘法放大为天文数字虚拟分片）；validate() L53-69 对 DesiredCount/VirtualPerPhysical 均无上限校验 → 创建索引时物理资源耗尽 → 容器挂起。

## Impact
单条未经认证即可发送的 schema 创建请求即可令单节点 Weaviate 完全不可用（无校验上限的乘法放大），构成廉价 DoS 面；恢复需重启容器。

## Novelty Gate
grade: NOVEL (no_known_hits, confidence HIGH, endorsement true)
