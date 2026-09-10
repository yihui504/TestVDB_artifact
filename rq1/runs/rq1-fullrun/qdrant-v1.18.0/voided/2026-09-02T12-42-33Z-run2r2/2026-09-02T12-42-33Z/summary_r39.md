# R39 Summary — chunk_points+query(TMA#1 大块;32 脚本 14 候选)

- 生成:32 脚本(bnd 13+state 9+sem 10);8 单元全覆盖+TMA 两 mandate
  (min_should 结果集语义+嵌套 filter);spec-vs-doc 漂移留痕×2
  (ACORN 命名 acorn_scale vs params.acorn.*;next_page_offset 不在发布 schema)
- 执行:32/32(30 exit0);竞速 5s;总 ~51s
- 引文核验:verify_chain_quotes 拦 4 mismatch( || 拼接/label 前缀混写)
  全打回 builder 修复(仅换 assertion_text_quoted 逐字子串)复检 PASS
- 判定:14 候选两批 auditor(7+7,>12 硬上限首拆);
  6 DEFECT / 8 NOT_DEFECT / 0 NME;A 机械全裁零翻案
- 累计:61 DEFECT / 52 NOT / 0 NME(39/80)

- 6 DEFECT 分族:
  * hnsw_ef=0 minimum-1 违反 200 受用(range_002;OpenAPI min:0
    doc 疑点留人工——hnswef_001)
  * query 缺失无 prefetch→400 vs 契约 id 序返回(behavioral_004;
    维护者 400 conformance test 疑点留人工——noid_order_001 + id_order_001 F5)
  * variant 矩阵:域成员 discover 变体 400(type_001;serde no-default
    ——variant_matrix_001)
  * by-id lookup 合法请求 400:using-substitution vs 文档 fallback
    (state_001——byid_mismatch_002)
  * 生命周期竞速:raced 500 顶掉文档 404(lifecycle_008;
    D 盲区命中 try_join_all cancellation)
- 8 NOT 三主题:#9255 家族×3(limit/offset/offset_exact——next_page_offset
  系 script 期望非承诺字段)+ score oracle×3(1/(1+d) 系脚本自造,
  distance-score by design)+ envelope should=对象(OpenAPI anyOf 许可
  +源码 by-design,D 锚命中)+ byid_lookup(源码故意排除)
- 分布:cat range=4/type=2/state=2/other=6(other=6 new-class 信号);
  fp both=8;cc strict 6/rejected 8/exploratory 0
- 人工复核标记:hnswef_001(doc min:0)+ noid_order/id_order
  (维护者 400-test)——E2 规则留痕未改判定
