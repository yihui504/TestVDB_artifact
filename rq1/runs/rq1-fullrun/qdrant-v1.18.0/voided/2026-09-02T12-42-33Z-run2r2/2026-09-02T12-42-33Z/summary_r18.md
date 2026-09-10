# R18 Summary — chunk_facet(facet 幽灵桶轮)

- 生成:14 脚本(bnd 4/state 5/sem 5);C3 一次全绿;日志落 session 根
- 执行:14/14(13 exit0/1 exit1);resource 大 limit 探针容器存活
- 判定:0 DEFECT / 1 NOT / 0 NME
- state_facet_002:delete 全 C 后 exact=true facet 保留 {C:0} 幽灵桶——
  源码实证(remove_point 不清空键 + exact_facet 无 count>0 守卫 vs
  approximate 面有显式过滤)**真实面间不对称**;但契约 doc-silent
  (FacetValueHit.count min 0 无缺席语句)violates=false→机械 REFUTED;
  auditor doubt 记录(建议 maintainer issue 级 triage,非契约缺陷)
- 累计:48 DEFECT / 23 NOT / 0 NME(18/80)
