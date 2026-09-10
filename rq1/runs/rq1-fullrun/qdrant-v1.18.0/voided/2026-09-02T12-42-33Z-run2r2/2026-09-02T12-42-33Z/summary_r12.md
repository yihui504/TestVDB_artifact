# R12 Summary — chunk_collections+delete(DELETE 幻影成功轮)

- 生成:16 脚本(bnd 5/state 5/sem 6);C3 一次全绿
- 执行:16/16(9 exit0/7 非零);残留循环预检零;内存 174MiB
- 判定:6 DEFECT / 0 NOT / 0 NME
- **6 DEFECT 两族**:
  * DELETE never-created/just-deleted/unicode → 200 {result:false}×4
    (断言 404 not 200;源码 Ok(false)→200,404 机制同 crate 未用于 delete;
    GET 面同名 404 对照;doc 层断——404 条款系提取 over-claim,文档只记
    200;RFC 9110 幂等抗辩 unannotated 留人工)
  * **by-alias DELETE no-op×2**(sem005+st005):200 result:false+原集合
    存活+映射不变——写路径不走 resolve_name(读面走)——**run2r #1
    defect-17 精确复现**;concept doc "All queries using an alias" 为
    doc 侧钩子
- 人工复核标记:404 条款 over-claim(R1/R3/R12 三度 J1①)+ RFC 幂等
- 累计:44 DEFECT / 21 NOT / 0 NME(12/80 块)
