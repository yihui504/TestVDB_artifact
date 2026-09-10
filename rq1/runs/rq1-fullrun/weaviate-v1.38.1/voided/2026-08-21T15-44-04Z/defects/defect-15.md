# Defect 15: int 属性 null 独被 200 接受（同批 5 种类型错误全 422）

## Metadata
- defect_id: boundary_property_type_confusion_012
- type: Type1_IllegalSuccess
- param: properties.<int>.null
- novelty: NOVEL
- Endpoint: POST /objects (int property n + id)
- Verdict: DEFECT (A=NEUTRAL→GREY_ZONE 机械 B=CONFIRMED, C=CONFIRMED, D=NO_SIGNAL)

## Reproduction (curl)
```bash
curl -s -X POST "http://localhost:8080/v1/objects" \
  -H "Content-Type: application/json" \
  -d '{"class":"BndTypeC","properties":{"n":null}}'
# -> HTTP 200 (accepted)
# 对照（同批全部正确 422）：
#   n="12"  -> 422 "invalid object: invalid integer property 'n' ... requires an ..."
#   n=1.5   -> 422；n=true -> 422；n=[] -> 422；n={} -> 422
# 次现象：id="" -> 200 returned_id=ab6ffccd-...（随机 UUID，文档化 by-design，不计入）
```

## Expected vs Actual
- Expected: int 属性 n 的类型检查应覆盖 null（5 种非法类型 '12'/1.5/true/[]/{} 均被 422 拒绝，唯独 null 漏网）。
- Actual: null 独被 200 接受——同批类型对照组自相矛盾，非一致性设计。

## Evidence Chain
- Ring 1 (Contract Clause 契约条款) constraint_id: 泛锚（boundary；实际引用 openapi-specs/schema.json data_types.Object.id required UUID + int 属性类型）
- Ring 2 (Document Reference 文档引用) doc_verification: DOC_PARTIAL（版本匹配 PASS；契约无 int-null 专项约束）
- Ring 3 (Actual Behavior 实际行为, HTTP Response 见 log) Script: debate_logs/boundary_property_type_confusion_012.py
- Log: debate_logs/output_boundary_property_type_confusion_012.log（n=None -> 200；5 种类型错误 -> 422）
- 源码 文件:行号+摘录: usecases/objects/validation/properties_validation.go 对 nil 值跳过类型检查（其余 '12'/1.5/true/[]/{} 均报 "invalid integer property"）；usecases/objects/add.go:145-158 checkIDOrAssignNew：`if id == "" { validatedID, err := generateUUID() ... }`——空 id 先被替换为随机 UUID（by-design，静默）；add.go:206-211 validateUUID 之后 parse 的已是合法 UUID。

## Impact
int 属性的 null 值绕过类型校验进入存储，与 422 拒绝的其他非法类型行为不一致；依赖类型严格性的下游（schema 演进、迁移、聚合）可能遇到未预期的 null。

## Novelty Gate
grade: NOVEL (no_known_hits, confidence HIGH, endorsement true)
