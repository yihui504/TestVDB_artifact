# Defect 8: cleanupIntervalSeconds 同函数校验不对称——-1 走 422、10^12 走 200、0 静默归 60

## Metadata
- defect_id: boundary_bm25_params_007
- type: Type1_IllegalSuccess
- param: invertedIndexConfig.cleanupIntervalSeconds
- novelty: NOVEL
- Endpoint: POST /v1/schema
- Verdict: DEFECT (A=NEUTRAL→GREY_ZONE 机械 B=CONFIRMED, C=CONFIRMED, D=NO_SIGNAL)

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:8080/v1/schema" \
  -H "Content-Type: application/json" \
  -d '{"class":"BndBm25","vectorizer":"none","invertedIndexConfig":{"cleanupIntervalSeconds":1000000000000,"bm25":{"b":0.75,"k1":1.2}}}'
# -> HTTP 200；readback persisted cleanup=1000000000000（~31000 年，verbatim）
# 对照：cleanupIntervalSeconds=-1 -> 422 "cleanup interval seconds must be > 0"
#       bm25 b=-0.5 / b=1.5 / k1=-1.2 -> 422（同函数有界校验存在）
#       cleanupIntervalSeconds=0 -> 200 但静默归一为默认 60
```

## Expected vs Actual
- Expected: 同一 ValidateConfig 内，负值已设下界校验，巨值（10^12 秒 > 31000 年）应有 sanity cap 或 4xx；0 应显式处理而非静默归一。
- Actual: 10^12 verbatim 200 持久化；0 静默变换为 60——同函数三态行为不一致（422 / 200 verbatim / 200 静默归一）。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: 泛锚（族级：源码错误文案 "cleanup interval seconds must be > 0"，inverted/config.go ValidateConfig）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL（源码锚本地核对；无专属 constraint_id）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_logs/boundary_bm25_params_007.py
- Log: debate_logs/output_boundary_bm25_params_007.log（6 变体确定性）
- 源码 文件:行号+摘录: adapters/repos/db/inverted/config.go L27-31 `func ValidateConfig(conf *models.InvertedIndexConfig) error { if conf.CleanupIntervalSeconds < 0 { return errors.Errorf("cleanup interval seconds must be > 0") }`——仅下界检查无上界；L121-126 `if u.K1 < 0 { ... "BM25.k1 must be >= 0" }; if b > 1 || b < 0 { ... "BM25.b must be >= 0 and <= 1" }`——同函数对 b/k1 均设界，不对称证实。

## Impact
误配 10^12 秒的清理间隔会被静默接受，Tombstone/过期数据清理实际永不发生，磁盘与索引膨胀；0 与巨值两种配置错误均无告警，用户无法察觉。

## Novelty Gate
grade: NOVEL (no_known_hits, confidence HIGH, endorsement true)
