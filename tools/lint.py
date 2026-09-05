#!/usr/bin/env python3
"""위키 건강검진 — 기계적으로 검사 가능한 규칙만 확인한다.

이 파일은 `.claude/skills/lint/SKILL.md`의 규칙을 코드로 옮긴 것이다.
**규칙을 고치면 이 파일도 같은 커밋에서 고친다.** 둘이 갈라지면 오탐이 난다.

판단이 필요한 체크(모순 판정, 묶기 제안, 원본 근거 분량)는 여기서 하지 않는다.
사람과 에이전트의 몫이다.

    python tools/lint.py            결과를 reports/ 에 저장
    python tools/lint.py --stdout   화면에도 출력
"""
import io, os, re, sys, json, glob, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
NL = chr(10)
TODAY = datetime.date.today()

# 고유명사·약어는 영문 태그를 허용한다 (context/위키 규약.md 참조)
PROPER = set("""Sysmon Zotero Obsidian Auto-Prov Flash MAGIC Kairos PROV-LLM
LLM APT DSPM RAG STIX CVE CWE CPE CAPEC MCP SPARQL OWL OpenC2 CTIO
AI ML SOC IaC NIST OWASP DARPA GPT LLaMA RoBERTa DBStream""".split())

PREFIX_AXIS = {'(AI활용)': 'ai-for-security', '(AI보호)': 'securing-ai'}

res = []
def rep(sev, num, what, where, how):
    res.append((sev, str(num), what, where, how))

def load(p):
    s = io.open(p, encoding='utf-8').read()
    e = s.find(NL + '---', 3)
    return (s[:e], s[e:]) if e > 0 else ('', s)

def links(body):
    """인라인 코드 안의 [[예시]]는 링크로 세지 않는다."""
    return [x.strip() for x in re.findall(r'\[\[([^\]|#]+)', re.sub(r'`[^`]*`', '', body))]

# ── 대상 수집 (SKILL.md의 제외 규칙) ────────────────────────────
active, ops = {}, {}
for p in sorted(glob.glob('wiki/*.md')):
    b = os.path.basename(p)[:-3]
    if b == 'CLAUDE' or '.example' in b:          # 규칙 문서·공개용 템플릿 제외
        continue
    (ops if b in ('index', 'log') else active)[b] = load(p) + (p,)

arch = {}
for p in glob.glob('wiki/_archive/*.md'):
    if os.path.basename(p) != 'README.md':        # 폴더 설명서 제외
        arch[os.path.basename(p)[:-3]] = load(p) + (p,)

ctx = set(os.path.basename(p)[:-3] for p in glob.glob('context/*.md') + glob.glob('docs/*.md'))
ctx.add('홈')
names = set(active) | set(ops) | ctx | set(os.path.basename(p) for p in glob.glob('*.base'))

idx_body = ops['index'][1]
todo_sec = idx_body[idx_body.find('## 아직 없는 페이지'):idx_body.find('## 메타')]
todo = set(t.strip() for t in re.findall(r'\[\[([^\]|#]+)', todo_sec))

inbound = dict((n, 0) for n in active)
todo_ref = {}
for n, (fm, body, p) in list(active.items()) + list(ops.items()):
    for t in set(links(body)):
        if t in inbound and t != n:
            inbound[t] += 1
        if t in todo:
            todo_ref.setdefault(t, []).append(n)

# ── 위키 페이지 검사 ──────────────────────────────────────────
for n, (fm, body, p) in active.items():
    if 'pinned: true' in fm:                      # 손으로 쓴 페이지는 검사 대상 아님
        continue
    L = links(body)
    for t in set(L):
        if t in arch:
            rep('E', 26, '[[' + t + ']] 폐기 페이지 참조', p, '대체 페이지로 링크 변경')
        elif t not in names and t not in todo:
            rep('E', 1, '[[' + t + ']] 깨진 링크', p, 'index 아직없는페이지 등록 또는 생성')
    if len(set(t for t in L if t in active and t != n)) < 2:
        rep('E', 25, '유효 링크 2개 미만', p, '관련 페이지 링크 추가 또는 통합')

    if 'contested:' not in fm or 'contradictions:' not in fm:
        rep('W', 24, 'contested/contradictions 필드 없음', p, 'frontmatter 추가')
    ct = re.search(r'^contested:\s*true', fm, re.M) is not None
    cal = '[!conflict]' in body
    if ct != cal and (ct or cal):
        rep('E', 22, 'contested=%s 인데 콜아웃=%s' % (ct, cal), p, '둘을 일치시킨다')
    m = re.search(r'^contradictions:\s*\[([^\]]*)\]', fm, re.M)
    if m and m.group(1).strip():
        for other in [x.strip().strip('"').strip("'") for x in m.group(1).split(',')]:
            if other in active and n not in active[other][0]:
                rep('E', 23, other + '가 나를 되짚지 않음', p, other + '에 ' + n + ' 추가')

    srcs = re.findall(r'(raw/[^\s]+\.md|[a-z]+\d{4}[A-Za-z]+)', fm)
    st = re.search(r'^status:\s*(\w+)', fm, re.M)
    if st and st.group(1) == 'stable' and not srcs:
        rep('E', 9, 'source 없이 status: stable', p, '출처를 채우거나 draft로')
    if not re.search(r'(ai-for-security|securing-ai|both)', fm):
        rep('W', 10, 'axis 태그 없음', p, 'tags에 축 태그 추가')

    if n.startswith('('):
        pre = n[:n.find(')') + 1]
        exp = PREFIX_AXIS.get(pre)
        if exp and exp not in fm:
            rep('E', '21f', '접두어와 축 불일치: ' + pre, p, '접두어 또는 tags 수정')
    else:
        rep('E', '21g', '축 접두어 없음', p, '(AI활용)/(AI보호)/(공통)/(기타) 부착')

    mk = set(re.findall(r'\^\[([^\]]+)\]', body))
    for k in mk:
        base = k.split(',')[0].strip()
        if base not in fm:
            rep('E', 20, '마커가 source에 없음: ' + base[:34], p, 'source 추가 또는 마커 제거')
    if len(srcs) >= 2 and not mk:
        rep('W', 21, '출처 2개 이상인데 마커 0개', p, '주장마다 마커 부착')

    ms = re.search(r'## 한 줄 요약\s*\n+(.+?)(?=\n\n|\n#|\n>)', body, re.S)
    if not ms:
        rep('W', 15, '한 줄 요약 없음', p, '첫 섹션으로 추가')
    elif len(re.findall(r'다\.', ms.group(1))) >= 2:
        rep('W', 15, '한 줄 요약이 2문장 이상', p, '한 문장으로 압축')
    if 'description:' not in fm:
        rep('W', '15b', 'description 없음', p, 'frontmatter에 추가')

    d = None
    mu = re.search(r'^updated:\s*(\d{4})-(\d{2})-(\d{2})', fm, re.M)
    if mu:
        d = datetime.date(int(mu.group(1)), int(mu.group(2)), int(mu.group(3)))
        if (TODAY - d).days > 180:
            rep('W', 6, 'updated ' + str(d) + ' (6개월 초과)', p, '내용 확인 후 갱신')

    ns = 'needs_source: true' in fm
    if ns and len(srcs) < 2:
        rep('I', 17, '보강 대기 (출처 1개)', p, '자료 추가 후 needs_source 제거')
        if d and (TODAY - d).days > 90:
            rep('W', 18, '3개월 경과 — 병합 검토', p, '통합 제안')
    elif ns:
        rep('W', 17, '출처 2개인데 needs_source 남음', p, 'needs_source 제거')

    def sec(title):
        """같은 제목의 절을 전부 합산한다. 하나만 재면 오탐이 난다."""
        tot = 0
        for mm in re.finditer(r'^## ' + title + r'.*$', body, re.M):
            j = body.find(NL + '## ', mm.start() + 3)
            tot += len(body[mm.start():(j if j > 0 else len(body))].encode('utf-8'))
        return tot
    a, bb = sec('원문 요약'), sec('원문 밖')
    if a and bb and bb > a and not ns:            # 17번이 걸린 페이지는 중복 보고하지 않는다
        rep('W', 19, '원문밖(%dB) > 원문요약(%dB)' % (bb, a), p, '내 정리 축소')

for n, c in inbound.items():
    if c == 0:
        rep('W', 4, 'inbound 링크 0 (고아)', active[n][2], 'MOC나 관련 페이지에서 링크')

# ── index 정합성 ─────────────────────────────────────────────
head = idx_body[:idx_body.find('## 아직 없는 페이지')]
listed = set(t.strip() for t in re.findall(r'\[\[([^\]|#]+)', re.sub(r'`[^`]*`', '', head)))
for n in sorted(set(active) - listed):
    rep('E', 2, 'index 미등록: ' + n, 'wiki/index.md', '한 줄 추가')
for n in sorted(listed - set(active) - set(['log'])):
    rep('E', 2, 'index에 있는데 파일 없음: ' + n, 'wiki/index.md', '줄 제거')
for ln in idx_body.split(NL):
    mm = re.match(r'- \[\[([^\]]+)\]\].*\((\w+)\)\s*$', ln.strip())
    if mm and mm.group(1) in active:
        r = re.search(r'^status:\s*(\w+)', active[mm.group(1)][0], re.M)
        if r and r.group(1) != mm.group(2):
            rep('E', 2, 'status 불일치: ' + mm.group(1), 'wiki/index.md', 'index 표기 수정')
    if ln.startswith('- [[') and len(ln) > 120:
        rep('W', 14, 'index 줄 ' + str(len(ln)) + '자', 'wiki/index.md', '요약 축약')

# ── _archive ────────────────────────────────────────────────
for n, (fm, body, p) in arch.items():
    if n in listed:
        rep('E', 27, '폐기 페이지가 index에 등록됨', p, 'index에서 제거')
    if 'archived:' not in fm or 'superseded_by:' not in fm:
        rep('W', 28, 'archived/superseded_by 없음', p, '폐기 메타 추가')

# ── raw 원본 ────────────────────────────────────────────────
tagcnt = {}
for p in glob.glob('raw/**/*.md', recursive=True):
    if os.path.basename(p) == 'CLAUDE.md':
        continue
    s = io.open(p, encoding='utf-8').read()
    if 'ingested: false' in s:
        rep('I', 8, '미인제스트 원본', p, '/ingest 실행')
    elif '주제/' not in s:
        rep('W', '21b', '주제 태그 없음', p, '주제/* 태그 부착')
    if re.search(r'^topic:', s, re.M):
        rep('E', '21e', 'tags 밖 topic 필드', p, 'tags 안으로 이동')
    if re.search(r'^type: (paper|book|video)', s, re.M) and re.search(r'^cite_key:\s*$', s, re.M):
        rep('W', 12, 'cite_key 비어 있음', p, '인용키 부여')
    if re.search(r'^why:\s*$', s, re.M):
        rep('W', 11, 'why 비어 있음', p, 'ingest 때 사용자에게 묻는다')
    for t in set(re.findall(r'주제/[^\s]+', s)):
        t = t.strip('"').strip("'").rstrip(',')
        tagcnt[t] = tagcnt.get(t, 0) + 1
        if re.match(r'^주제/[A-Za-z0-9&.-]+$', t):
            if not any(x in PROPER for x in t[3:].split('-')):
                rep('W', '21d', '영문 주제 태그: ' + t, p, '한국어로 통일 (고유명사는 예외)')
for t, c in sorted(tagcnt.items()):
    if c == 1:
        rep('I', '21c', '1회만 쓰인 태그: ' + t, 'raw/', '재사용 또는 통합 검토')

# ── 보고서 ──────────────────────────────────────────────────
LB = ['', '']
LB[0] = '# 위키 건강검진'
order = {'E': 0, 'W': 1, 'I': 2}
res.sort(key=lambda r: (order[r[0]], r[1]))
lines = ['# 위키 건강검진', '', '실행: ' + str(TODAY), '',
         '| 심각도 | 건수 |', '|---|---|']
for sev, label in (('E', '🔴 Error'), ('W', '🟡 Warning'), ('I', 'ℹ️ Info')):
    lines.append('| ' + label + ' | ' + str(len([r for r in res if r[0] == sev])) + ' |')
for sev, label in (('E', '🔴 Error'), ('W', '🟡 Warning'), ('I', 'ℹ️ Info')):
    rows = [r for r in res if r[0] == sev]
    lines += ['', '## ' + label + ' (' + str(len(rows)) + '건)', '']
    if not rows:
        lines.append('없음')
        continue
    lines += ['| 체크 | 무엇이 | 어디서 | 어떻게 |', '|---|---|---|---|']
    for s, num, what, where, how in rows:
        lines.append('| %s | %s | `%s` | %s |' % (num, what, where.replace('\\', '/'), how))

# 체크 5 — 참조 횟수만 센다. 원본 근거 분량 판정은 사람/에이전트가 한다.
lines += ['', '## 체크 5 — stub 후보 (참조 횟수)', '',
          '> 원본 근거 분량은 이 스크립트가 재지 않는다. `/lint` 스킬의 판정표를 따라 에이전트가 확인한다.',
          '', '| 미생성 페이지 | 참조 | 어디서 |', '|---|---|---|']
for t, srcs in sorted(todo_ref.items(), key=lambda x: (-len(x[1]), x[0])):
    lines.append('| [[%s]] | %d곳 | %s |' % (t, len(srcs), ', '.join(sorted(srcs))))

os.path.isdir('reports') or os.makedirs('reports')
out = 'reports/lint-' + str(TODAY) + '.md'
io.open(out, 'w', encoding='utf-8').write(NL.join(lines) + NL)

# 웹 UI 등 다른 도구가 읽을 수 있게 JSON도 남긴다 (같은 검사 결과, 다른 형식)
payload = {
    'date': str(TODAY),
    'counts': dict((s, len([r for r in res if r[0] == s])) for s in 'EWI'),
    'findings': [{'severity': s, 'check': n, 'what': w,
                  'where': p2.replace(chr(92), '/'), 'how': h}
                 for s, n, w, p2, h in res],
    'stubs': [{'name': t, 'refs': len(v), 'from': sorted(v)}
              for t, v in sorted(todo_ref.items(), key=lambda x: (-len(x[1]), x[0]))],
}
io.open('reports/lint-' + str(TODAY) + '.json', 'w', encoding='utf-8').write(
    json.dumps(payload, ensure_ascii=False, indent=2))

summary = 'E=%d W=%d I=%d  ->  %s' % (
    len([r for r in res if r[0] == 'E']),
    len([r for r in res if r[0] == 'W']),
    len([r for r in res if r[0] == 'I']), out)
print(summary)
if '--stdout' in sys.argv:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    print(NL.join(lines))
