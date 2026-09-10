#!/usr/bin/env python3
"""查 3 个 dup issue (52308/52310/52312) 的母 issue 状态, 收尾 Phase 1 待补项."""
import urllib.request, json, time, re

REPO = 'milvus-io/milvus'
DUPS = [52308, 52310, 52312]
HDRS = {'User-Agent': 'testvdb'}


def get(url):
    req = urllib.request.Request(url, headers=HDRS)
    return json.load(urllib.request.urlopen(req))


def collect_parents():
    """从 dup issue 的 body + maintainer comments 提取母 issue 编号."""
    found = {}
    for num in DUPS:
        iss = get(f'https://api.github.com/repos/{REPO}/issues/{num}')
        refs = set(re.findall(r'#(\d{4,6})', iss.get('body') or ''))
        refs.discard(str(num))
        cmts = get(f'https://api.github.com/repos/{REPO}/issues/{num}/comments?per_page=100')
        for c in cmts:
            if c['user']['login'] == 'yanliang567':
                refs |= set(re.findall(r'#(\d{4,6})', c['body']))
                refs.discard(str(num))
        found[num] = sorted(refs, key=int)
        print(f'#{num} title: {iss["title"][:80]}')
        print(f'  candidates: {found[num]}')
        time.sleep(0.5)
    return found


def check_parent(num):
    """查母 issue 状态: state, state_reason, 有无 cross-ref PR."""
    iss = get(f'https://api.github.com/repos/{REPO}/issues/{num}')
    pr = iss.get('pull_request')
    state = iss['state']
    reason = iss.get('state_reason')
    title = iss['title'][:80]
    # timeline 找 cross-referenced PR
    tls = get(f'https://api.github.com/repos/{REPO}/issues/{num}/timeline?per_page=100')
    prs = []
    for e in tls:
        src = e.get('source', {}).get('issue', {})
        if e['event'] == 'cross-referenced' and src.get('pull_request') is not None:
            prs.append((src.get('number'), src.get('title', '')[:60]))
    print(f'  #{num} ({state}/{reason}) {title}')
    if pr:
        print(f'    cross-ref PRs: {prs}')
    else:
        print(f'    no cross-ref PR')
    return num, state, reason, prs


# 先确认 rate limit
d = get('https://api.github.com/rate_limit')
rem = d['resources']['core']['remaining']
print(f'rate limit remaining: {rem}\n')
if rem < 15:
    wait = d['resources']['core']['reset'] - time.time() + 5
    print(f'  insufficient, sleeping {wait:.0f}s to reset')
    time.sleep(wait)

parents = collect_parents()
print('\n== parent issues ==')
for num, cands in parents.items():
    for p in cands:
        check_parent(int(p))
        time.sleep(0.5)
