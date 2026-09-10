# R4 Summary — chunk_cluster+collection+info(2 单元)

- 生成:15 脚本(bnd 5/state 4/sem 6);classify transport_probe 3 处返工
  (根因:classifier 只识别 safe_request/requests.x 形态,rt.request 不可见
  ——机制坑挂账;workaround=safe_request 包装器)
- 执行:15/15(10 exit0/5 exit1);内存峰值 178MiB 无险
- 判定:5 DEFECT / 1 NOT / 0 NME
- **5 DEFECT 全同信号**:200 响应缺 resharding_operations vs 契约无条件
  containment;机械层 CONFIRMED×5(violates=true 字面),**五链全部记录
  by_design doubt**(源码 TODO+serde skip+OpenAPI nullable 非 required+
  上游测试断言缺席)——E2 反翻案规则保持 DEFECT,人工复核定夺
- **系统性发现:formalizer containment 断言过度主张**——doc example 含字段
  ≠ required;契约应消费 OpenAPI required 数组(J1 契约失真家族新成员,
  formalizer 系统性改进项)
- 1 NOT(bnd003):错路由族破案(wire capture:urllib3 把 .. 溶解为 /cluster/;
  脚本路由 /cluster/collection/{name} 不存在——chunk 标签路径推导不可靠,
  应强制消费 raw_knowledge url 字段;4 个 SCRIPT_ERROR 同根)
- 累计:25 候选 17 DEFECT / 8 NOT / 0 NME
