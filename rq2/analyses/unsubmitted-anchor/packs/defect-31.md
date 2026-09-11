# 候选缺陷 defect-31

[vendor=qdrant endpoint=unknown]

--- 观察到的行为（observed） ---

- [out-of-domain [256, 0, 1, 2]] status=200 raw={"result":{"operation_id":2,"status":"completed"},"status":"ok","time":0.005555691}
- [uint8 count] status=200 count=3 (positive arm: 3 in-range integer vectors accepted)
- [uint8 read-back] status=404 raw= (points+get face returned 404 with empty body; the exactness/read-back wrap-saturation comparison leg could not execute — the R6-described detector fell back to count-drift evidence; cause undetermined, target no longer live to reproduce)
- [count after [256, 0, 1, 2]] status=200 count=4 (accepted out-of-domain write materialized; snapshot before was 3)
- [out-of-domain [0, -1, 1, 2]] status=200 raw={"result":{"operation_id":3,"status":"completed"},"status":"ok","time":0.005297496}
- [count after [0, -1, 1, 2]] status=200 count=5
- [out-of-domain [0, 1, 1.5, 2]] status=200 raw={"result":{"operation_id":4,"status":"completed"},"status":"ok","time":0.003318622}

--- 契约（expected，来自该版本文档/契约） ---

assertion: datatype in [float32, uint8, float16, turbo4]; uint8 dense vectors hold integers in range 0-255; turbo4 cannot be configured for sparse vectors
source_url: 
doc_version: 
