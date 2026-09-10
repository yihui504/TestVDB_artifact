# R13 Summary — chunk_collections+exists(exists 面干净)

- 生成:16 脚本(bnd 6/state 5/sem 5);C3 一次全绿
- 执行:16/16 全 exit0;内存 158MiB
- 判定:0 DEFECT / 0 NOT / 0 NME——**零候选轮**:exists 语义全对
  (live→200 true/never-created→200 false/删除翻 false/重建翻 true/
  alias 解析正确/形状 {result:{exists:bool}} 合规/探针稳定零翻面)
- 注:16 NO_DEFECT 无候选(extract_candidates 无新增)——exists 是
  本 session 迄今最干净面;run2r #1 R5 的 exists-shape 形状断言
  {result:{exists:bool}} 在本代际实测合规
- 累计:44 DEFECT / 21 NOT / 0 NME(13/80 块)
