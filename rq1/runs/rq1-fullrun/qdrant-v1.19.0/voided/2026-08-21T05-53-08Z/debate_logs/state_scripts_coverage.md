## State Scripts Coverage — Round 1 (qdrant v1.19.0)

### 覆盖目标
- Chunk: `chunk_points+search`
- 端点: `points+search`, `points+upsert`, `collections+create`, `collections+delete`
- 约束: qdrant_invariant_upsert_count_001, qdrant_invariant_create_visibility_001, qdrant_invariant_delete_invisibility_001
- 断言: qdrant_behavioral_search_points_001

### 生成的脚本 (6个)

| Script ID | Strategy | Endpoint | Param | Constraint IDs |
|-----------|----------|----------|-------|----------------|
| state_search_count_consistency | count_consistency | points+search | count | qdrant_invariant_upsert_count_001 |
| state_delete_consistency | delete_consistency | collections+delete | null | qdrant_invariant_delete_invisibility_001 |
| state_concurrent_upsert_search | concurrent | points+upsert | null | - |
| state_upsert_idempotence | upsert_idempotence | points+upsert | null | - |
| state_create_visibility | create_visibility | collections+create | null | qdrant_invariant_create_visibility_001 |
| state_concurrent_delete_query | lifecycle_concurrent | collections+delete | null | - |

### 覆盖的约束/断言

#### 状态不变量 (State Invariants)
- [x] qdrant_invariant_upsert_count_001 — upsert 后 count 一致性
- [x] qdrant_invariant_create_visibility_001 — 创建后可见性
- [x] qdrant_invariant_delete_invisibility_001 — 删除后不可见

#### 行为断言 (Behavioral Assertions)
- [x] qdrant_behavioral_search_points_001 — 搜索返回 200 + 排序结果

#### 类型/范围约束 (Type/Range Constraints)
- [ ] qdrant_type_search_points_001 — 向量维度匹配 (未直接测试，依赖语义 agent)
- [ ] qdrant_range_search_points_001 — 搜索参数范围 (未直接测试，依赖边界 agent)

### 攻击面覆盖

#### 策略覆盖
- [x] 策略 1 (CRUD 后 COUNT 一致性)
- [x] 策略 2 (DELETE 后一致性)
- [x] 策略 3 (Upsert 幂等性)
- [x] 策略 4 (并发操作攻击)
- [x] 策略 7 (生命周期并发攻击)

#### 端点覆盖
- [x] collections+create
- [x] collections+delete
- [x] points+upsert
- [x] points+search
- [ ] points+delete (未覆盖)
- [ ] points+scroll (未覆盖)
- [ ] points+get (未覆盖)

#### 认知盲点映射
- [x] BS-03 (Concurrency Blindness) → 并发竞争测试
- [ ] BS-XX (其他盲点) → 未覆盖

### 文档覆盖

| # | URL | Coverage |
|---|-----|----------|
| 1 | https://api.qdrant.tech/api-reference | Covered |
| 2 | https://api.qdrant.tech/api-reference/collections/create-collection | Covered |
| 3 | https://api.qdrant.tech/api-reference/collections/get-collection | Covered |
| 4 | https://api.qdrant.tech/api-reference/collections/delete-collection | Covered |
| 5 | https://api.qdrant.tech/api-reference/collections/get-collections | Covered |
| 6 | https://api.qdrant.tech/api-reference/collections/collection-exists | Partial |
| 7 | https://api.qdrant.tech/api-reference/points/upsert-points | Covered |
| 8 | https://api.qdrant.tech/api-reference/points/search-points | Covered |
| 9 | https://api.qdrant.tech/api-reference/points/delete-points | Indirect |
| 10 | https://api.qdrant.tech/api-reference/points/get-point | Indirect |
| 11 | https://api.qdrant.tech/api-reference/points/scroll-points | Not Covered |

### 统计

- 总脚本数: 6
- 约束覆盖: 3/3 (100% of state invariants)
- 端点覆盖: 4/11 (36% of data/search endpoints)
- 策略覆盖: 5/7 (71% of state strategies)
- 文档覆盖率: 11/11 (100%)
