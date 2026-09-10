# R21 Summary — chunk_index+create(2 单元;会话中断无损恢复)

- 生成:20 脚本(bnd 9/sem 5/state 6;上会话退出中断但产物全落盘)
- 执行:20/20(19 exit0);C3 全绿;executor 重建缺失 .executor.env
- 判定:1 DEFECT / 0 NOT——**field_schema=["keyword"] 数组形式 200 受理**
  =run2r #1 defect-18 复现(serde untagged positional visit_seq 宽容:
  Keyword(KeywordIndexParams) 尾字段全 default;[] 400 vs ["keyword"] 200
  签名;doc 声明 enum-or-objects 无数组形)
- index create 其余面合规(类型闭包/回读 echo/404 处置/并发建索引)
- 累计:49 DEFECT / 23 NOT / 0 NME(21/80)
