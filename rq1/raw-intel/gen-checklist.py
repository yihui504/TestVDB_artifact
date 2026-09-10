#!/usr/bin/env python3
"""生成人工核对清单: 分类标准 + 全部 124 issue 带证据摘要."""
import csv

CSV = r'<DESKTOP>\pipelinehost\data\vdbms-issues.csv'
OUT = r'<ARTIFACT_ROOT>\.paperpilot\phase1-raw\checklist.md'

# 32 个重分类 issue 的证据摘要 (number -> evidence)
EVID = {
    47763: 'maintainer xiaofan-luan: "final fix I made: Relaxed dynamic field key validation"',
    49890: 'timeline PR #50195 "fix: validate REST request timeout header" (xiaofan-luan), sre-ci-robot 关',
    51084: 'maintainer yanliang567: "i have made a pr to fix it"',
    51085: 'maintainer yanliang567: "i had pr to fix it"',
    9017: 'timvisee: "Fixed via PR #9320"',
    9039: 'timeline PR #9058 "validate vector dimensions before WAL write", generall 关',
    9045: 'timvisee: "Fixed in PR #9070, included in Qdrant 1.18.1"',
    9149: 'timvisee: "already covered by PR #9178"',
    11729: 'timeline PR #11824 "fix(sharding): reject negative desiredCount (gh-11729)", trengrj 关',
    12041: 'timeline PR #12049 "gh-12041 return 422 for batch delete", dirkkul 关',
    47752: 'foxspy 分析: ef validation 仅 HNSW path 生效, 小数据集 brute-force path 有缺口; 关时无 PR',
    47755: 'xiaofan-luan "suggestion is overall good" + zhengbuqian "misunderstanding of in expr"; 关时无 PR',
    52307: 'yanliang567: "closed as dup"',
    52308: 'yanliang567: "close as dep"',
    52310: 'yanliang567: "lets track the issue in the dup issues above"',
    52312: 'yanliang567: "closed as dup"',
    47635: 'yanliang567: "milvus 2.3 is very old, upgrade to 2.5.26/2.6.10" + stale[bot] 关',
    47636: 'yanliang567: "please retry on milvus 2.5.26 or 2.6.10" + stale[bot] 关',
    47766: '仅 assign @liliu-z 后无下文, stale[bot] 关',
    49059: 'xiaofan-luan "good suggestion", 社区 kailash360 认领后无下文, stale[bot] 关',
    49843: 'stale[bot] 30d 自动关, 无修复证据',
    50018: 'yanliang567: "not a big problem, could make an improvement" + stale[bot] 关',
    49844: 'MrPresent-Han: "not a real server-side bug... breaking validation"',
    50324: 'yanliang567: "sounds like a document issue, share the doc link"',
    9416: 'coszio: "not an unusable collection, allows payload-only collection"',
    9417: 'coszio: "See #9416" (同 9416 判定)',
    9418: 'coszio: "This is fine and expected... would be a breaking change"',
    9419: 'coszio: "supports null/object/array. fine and expected"',
    9420: 'coszio: "breaking change... not worth it"',
    11981: 'dudanogueira: "working as intended, OpenAPI claim does not hold"',
    9255: '0xDjole: "failed to reproduce on 1.18.1" (comment 提到 1.8.1 为笔误, 复测 1.18.1)',
    9373: 'generall: "not sure I am able to reproduce without exotic params"',
    47785: 'PR (Fixes #47729): 第一版 nprobe validation 修复, stale[bot] 关未 merge, 被 #51809 rewrite 取代',
    51809: 'PR (Fixes #47729): rewrite 版, xiaofan-luan 两轮 review + CI 全绿, 等 final approve',
}

CAT_ORDER = [
    ('TP_FIXED_PR', '真修复: timeline 有 cross-ref PR 或 maintainer 明说 fixed via PR'),
    ('TP_ACK_OPEN', 'bug 确认未修: open + maintainer triage/accepted label'),
    ('TP_ACK_CLOSED_NOFIX', 'bug 确认但关闭时无 PR'),
    ('TP_DUP_TRACKED', 'maintainer "closed as dup", bug 归母 issue 跟踪'),
    ('BY_DESIGN', 'by-design/wontfix label 或 state_reason=not_planned'),
    ('FP_BY_DESIGN', 'maintainer 评论反驳为设计行为 (label 无 by-design 但评论判定)'),
    ('FP_NOT_REPRO', 'maintainer 无法复现'),
    ('STALE_NO_FIX', 'stale[bot] 自动关, 无修复证据'),
    ('PENDING_SELF_LABELED', 'open + bug label, 无 maintainer accept'),
    ('SELF_CLOSED', 'closed, 无 bug label, closed_by=<submitter>'),
    ('OPEN_NO_LABEL', 'open, 无 bug label'),
    ('SELF_PR_OPEN', '自己提交的修复 PR, open (maintainer review 中)'),
    ('SELF_PR_CLOSED', '自己提交的修复 PR, 已关未 merge'),
]

rows = list(csv.reader(open(CSV, encoding='utf-8')))
data = [r for r in rows[1:]]

L = []
L.append('# Phase 1 issue 分类人工核对清单 (124 issues + 2 PRs = 126 条)\n')
L.append('生成: 2026-08-13 | 数据: pipelinehost/data/vdbms-issues.csv\n')
L.append('## 分类标准\n')
L.append('| 分类 | 硬判据 |')
L.append('|---|---|')
for cat, desc in CAT_ORDER:
    L.append(f'| `{cat}` | {desc} |')
L.append('')
L.append('核对方法: 每行 `- [ ]` 打钩=同意当前分类; 打 `x` 并注明新分类+理由。证据列给了判定依据。\n')

for vendor in ['milvus-io/milvus', 'qdrant/qdrant', 'weaviate/weaviate']:
    short = vendor.split('/')[1]
    L.append(f'## {vendor} ({sum(1 for r in data if r[0]==vendor)})')
    L.append('')
    for cat, _ in CAT_ORDER:
        items = [r for r in data if r[0] == vendor and r[4] == cat]
        if not items:
            continue
        L.append(f'### {cat} ({len(items)})')
        L.append('')
        for r in sorted(items, key=lambda x: int(x[1])):
            num, state, sr, title, labels = r[1], r[2], r[3], r[6], r[8]
            ev = EVID.get(int(num), f'{state}/{sr} | labels: {labels}' if labels else f'{state}/{sr}')
            L.append(f'- [ ] **#{num}** | `{cat}` | {title} | {ev}')
        L.append('')

open(OUT, 'w', encoding='utf-8').write('\n'.join(L))
print('wrote', OUT, f'{len(data)} issues')
