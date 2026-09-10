## Shape: ef_pairing_numeric_boundary (shape_type=numeric_boundary)

### 参数族枚举（按 parameter_family_rule: 遍历契约所有端点的 parameters，挑 int/number 类型字段，且属 vectorIndexConfig/replicationConfig 配对或数值面）

| 参数 | 端点 | 类型 | known_instance? | 探索值 |
|------|------|------|----------------|--------|
| dynamicEfMin | POST /schema | int (default 100) | ✓ (#weaviate_inferred_hnsw_ef_pairing_001, prior defect-1) | (在 inverted 里测过；novel 面 = 0/-1) |
| dynamicEfMax | POST /schema | int (default 500) | ✓ (#weaviate_inferred_hnsw_ef_pairing_001) | (novel 面 = -1, MinOnly, MaxOnly) |
| flatSearchCutoff | POST /schema | int (default 40000) | ✗ | -1, 0, 1e9, 12345.67(float) |
| maxConnections | POST /schema | int | ✗ | -1, "abc"(type) |
| efConstruction | POST /schema | int | ✗ | -1 |
| replicationFactor | POST /schema | int | ✗ | -1, 0, 2 |
| cleanupIntervalSeconds | POST /schema | int | ✗ | -1 |
| vectorCacheMaxObjects | POST /schema | int | ✗ | -1 |
| ef | POST /schema | int | ✗ | -1, 0 |

### novel_candidate 目标（排除 known_instance dynamicEfMin/dynamicEfMax 的 inverted/equal 主回归面）
- dynamicEfMin={0, -1} / dynamicEfMax={-1} / MinOnly / MaxOnly
- flatSearchCutoff={-1, 0, 1e9, float}
- maxConnections={-1, "abc"} / efConstruction={-1}
- replicationFactor={-1, 0, 2}

### 产出脚本（novel_candidate）
- boundary_schema_dynamicEf_equal.py (Min==Max)
- boundary_schema_dynamicEfMinOnly.py
- boundary_schema_dynamicEfMaxOnly.py
- boundary_schema_dynamicEfMin_negative.py
- boundary_schema_dynamicEfMax_negative.py
- boundary_schema_dynamicEfMin_zero.py
- boundary_schema_flatSearchCutoff_negative.py / _zero.py / _extreme.py / _float.py
- boundary_schema_maxConnections_negative.py / _type.py
- boundary_schema_efConstruction_negative.py
- boundary_schema_replicationFactor_negative.py / _zero.py / _gt_one.py
