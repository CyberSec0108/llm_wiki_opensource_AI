"""자동 인제스트 파이프라인 — `raw/`의 자료 하나를 위키에 반영한다.

**규칙을 여기에 복사하지 않는다.** `CLAUDE.md`와 `SKILL.md`를 읽어서
그대로 시스템 프롬프트로 넣는다. 규칙을 고치면 이 코드는 그대로 두면 된다.

터미널의 `/ingest`를 대체하지 않는다. 같은 규칙을 쓰는 두 번째 입구다.

    python tools/ingest.py                     대기 중인 것 목록
    python tools/ingest.py <경로>              인제스트
    python tools/ingest.py <경로> --dry-run    호출 없이 프롬프트만 확인
    python tools/ingest.py <경로> --plan-only  분석까지만, 파일은 안 건드림
"""

import datetime
import glob
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llm  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS = os.path.join(ROOT, 'reports')
REVIEW = os.path.join(ROOT, 'wiki', 'review.md')

# 시스템 프롬프트를 이루는 파일들. 순서가 곧 프롬프트 순서다.
# 앞쪽일수록 안정적인 내용을 둔다 — 캐시는 접두사 일치라서.
RULES = [
    'CLAUDE.md',
    'raw/CLAUDE.md',
    'wiki/CLAUDE.md',
    'context/위키 규약.md',
    'context/나의 핵심 맥락.md',
    '.claude/skills/ingest/SKILL.md',
]

# LLM이 만들어낼 수 있는 조치를 이것으로 제한한다.
# 열어두면 임의 작업이 큐에 쌓이고, 그걸 처리하는 규칙이 또 필요해진다.
ACTIONS = ('페이지 생성', '자료 수집', '건너뛰기', '모순 판정', 'cite_key 확정')



def _obj(props, req=None):
    """strict 스키마는 additionalProperties:false 와 완전한 required 를 요구한다."""
    return {'type': 'object', 'additionalProperties': False,
            'properties': props, 'required': req or list(props)}


def _arr(item):
    return {'type': 'array', 'items': item}


S = {'type': 'string'}
B = {'type': 'boolean'}

# 형식을 스키마로 강제한다. 프롬프트로만 부탁하면 싼 모델이 흘린다 —
# 실측에서 glm-5.3-flash 가 JSON 대신 산문을 뱉었다.
SCHEMA1 = _obj({
    'summary': S,
    'claims': _arr(_obj({'claim': S, 'evidence': S})),
    'axis_check': _obj({'stated': S, 'judged': S, 'agrees': B, 'why': S}),
    'topics': _arr(S),
    'update_targets': _arr(_obj({'page': S, 'what': S})),
    'new_page_candidates': _arr(_obj({
        'name': S, 'refs': {'type': 'integer'}, 'bytes': {'type': 'integer'},
        'passes': B, 'why': S})),
    'conflicts': _arr(_obj({'page': S, 'existing': S, 'new': S})),
})

SCHEMA2 = _obj({
    'edits': _arr(_obj({
        'page': S, 'mode': {'type': 'string', 'enum': ['update', 'create']},
        'content': S, 'why': S})),
    'review': _arr(_obj({
        'action': {'type': 'string', 'enum': list(ACTIONS)},
        'subject': S, 'detail': S})),
    'log': S,
})


def rd(p):
    with io.open(p, encoding='utf-8') as f:
        return f.read()


def fm_body(text):
    """frontmatter와 본문을 나눈다."""
    if not text.startswith('---'):
        return '', text
    e = text.find('\n---', 3)
    if e < 0:
        return '', text
    return text[4:e], text[e + 4:].lstrip('\n')


def fm_get(fm, key):
    m = re.search(r'^' + re.escape(key) + r':\s*(.*)$', fm, re.M)
    return m.group(1).strip().strip('"\'') if m else ''


def pending():
    """아직 위키에 안 들어간 자료."""
    out = []
    for p in sorted(glob.glob(os.path.join(ROOT, 'raw', '**', '*.md'), recursive=True)):
        if os.path.basename(p) == 'CLAUDE.md' or '.example' in p:
            continue
        fm, body = fm_body(rd(p))
        if fm_get(fm, 'ingested').lower() in ('true', 'yes'):
            continue
        out.append({'path': os.path.relpath(p, ROOT).replace('\\', '/'),
                    'title': fm_get(fm, 'title') or os.path.basename(p)[:-3],
                    'axis': fm_get(fm, 'axis'), 'why': fm_get(fm, 'why'),
                    'bytes': len(body.encode('utf-8'))})
    return out


def build_system():
    """규칙 문서를 이어붙여 시스템 프롬프트를 만든다.

    읽어서 넣기 때문에, 규칙이 바뀌면 다음 인제스트부터 자동으로 반영된다.
    """
    parts = ['다음은 이 볼트의 규칙 문서 전문이다. 전부 따른다.\n']
    for rel in RULES:
        p = os.path.join(ROOT, rel)
        if os.path.exists(p):
            parts.append('\n\n===== 파일: %s =====\n%s' % (rel, rd(p)))
    return ''.join(parts)


def wiki_state():
    """지금 위키에 뭐가 있는지. 새 페이지보다 기존 갱신이 우선이므로 반드시 준다."""
    rows = []
    for p in sorted(glob.glob(os.path.join(ROOT, 'wiki', '*.md'))):
        b = os.path.basename(p)[:-3]
        if b in ('CLAUDE', 'log', 'review') or '.example' in b:
            continue
        fm, body = fm_body(rd(p))
        rows.append('- [[%s]] · status:%s · %s' % (
            b, fm_get(fm, 'status') or '?', (fm_get(fm, 'description') or '')[:90]))
    idx = os.path.join(ROOT, 'wiki', 'index.md')
    return '\n'.join(rows), (rd(idx) if os.path.exists(idx) else '')


def progress(jid, **kw):
    """진행 상황을 파일로 남긴다. UI는 이 파일을 읽어 표시한다.

    파일이 정본이라는 원칙이 여기에도 적용된다 — 서버가 죽어도 기록이 남는다.
    """
    os.makedirs(REPORTS, exist_ok=True)
    p = os.path.join(REPORTS, 'ingest-%s.json' % jid)
    d = {}
    if os.path.exists(p):
        try:
            d = json.loads(rd(p))
        except ValueError:
            d = {}
    d.update(kw)
    d['at'] = datetime.datetime.now().isoformat(timespec='seconds')
    with io.open(p, 'w', encoding='utf-8') as f:
        f.write(json.dumps(d, ensure_ascii=False, indent=2))
    return d


STEP1 = """아래 자료를 분석하라. **위키를 아직 고치지 마라.** 분석만 한다.

## 자료 (%(path)s)
```
%(raw)s
```

## 지금 위키에 있는 페이지
%(pages)s

## index.md
```
%(index)s
```

다음 JSON만 출력하라. 설명·인사·코드블록 울타리 없이 JSON만.

{
  "summary": "이 자료가 무엇인지 두 문장",
  "claims": [{"claim": "핵심 주장", "evidence": "원문 근거 문장"}],
  "axis_check": {"stated": "자료에 적힌 axis", "judged": "본문을 읽고 판단한 axis",
                 "agrees": true, "why": "판단 근거"},
  "topics": ["주제/한국어-하이픈 형태의 태그"],
  "update_targets": [{"page": "기존 페이지 이름", "what": "무엇을 더할 수 있나"}],
  "new_page_candidates": [{"name": "후보 이름", "refs": 0, "bytes": 0,
                           "passes": false, "why": "생성 기준 통과 여부와 근거"}],
  "conflicts": [{"page": "기존 페이지", "existing": "기존 서술", "new": "자료의 서술"}]
}

규칙:
- `update_targets`를 `new_page_candidates`보다 우선한다. 기존 페이지 갱신이 먼저다.
- `new_page_candidates`의 `passes`는 `wiki/CLAUDE.md`의 생성 기준으로만 판정한다.
- `conflicts`는 **발견만 하고 판정하지 마라.** 어느 쪽이 옳은지 쓰지 마라.
- 자료에 없는 내용을 지어내지 마라."""

STEP2 = """앞서 분석한 자료를 위키에 반영할 **편집안**을 만들어라.

## 자료 (%(path)s)
```
%(raw)s
```

## 분석 결과
```json
%(analysis)s
```

## 갱신 대상 페이지 전문
%(targets)s

다음 JSON만 출력하라.

{
  "edits": [{"page": "페이지 이름", "mode": "update" 또는 "create",
             "content": "파일 전체 내용 (frontmatter 포함)",
             "why": "이 편집이 필요한 이유 한 줄"}],
  "review": [{"action": "%(actions)s 중 하나",
              "subject": "대상", "detail": "무엇을 결정해야 하나"}],
  "log": "wiki/log.md에 남길 한 줄 (날짜 제외)"
}

규칙:
- `mode: update`면 **기존 내용을 보존하고 더한다.** 지우지 마라.
- 모든 주장에 출처 마커를 단다. **이 자료의 마커는 `%(marker)s` 하나뿐이다.**
  다른 형식을 섞지 마라 — `source:` 에 없는 마커를 쓰면 검사에서 오류가 난다.
- `updated` 필드를 %(today)s 로 바꾼다.
- 판단이 필요한 것은 `edits`가 아니라 `review`에 넣는다 — 모순, axis 불일치,
  생성 기준 애매, cite_key 미확정.
- `review`의 `action`은 주어진 목록 밖의 값을 쓰지 마라."""


def run(rel, dry=False, plan_only=False, jid=None):
    jid = jid or datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    src = os.path.join(ROOT, rel)
    if not os.path.exists(src):
        raise SystemExit('없는 파일: ' + rel)

    system = build_system()
    pages, index = wiki_state()
    raw_text = rd(src)
    # 논문·책은 cite_key 로 인용한다(raw/CLAUDE.md). 없으면 경로를 쓴다.
    _fm, _ = fm_body(rd(src))
    _ck = fm_get(_fm, 'cite_key')
    marker = ('^[' + _ck + ', 위치]') if _ck else ('^[' + rel + ']')
    today = datetime.date.today().isoformat()

    progress(jid, path=rel, stage='읽기', step=1, of=4, done=False,
             system_bytes=len(system.encode('utf-8')))

    p1 = STEP1 % {'path': rel, 'raw': raw_text, 'pages': pages, 'index': index}

    if dry:
        est = (len(system) + len(p1)) // 3  # 한국어 혼합 대략치
        print('시스템 프롬프트  %6d B  (규칙 %d개 파일)' % (
            len(system.encode('utf-8')), len(RULES)))
        print('1단계 사용자     %6d B' % len(p1.encode('utf-8')))
        print('대략 입력 토큰   %6d' % est)
        print('\n호출 없이 종료했다. 실제 실행은 --dry-run 을 빼라.')
        progress(jid, stage='건조 실행', done=True)
        return {'dry': True, 'jid': jid}

    progress(jid, stage='분석', step=2, of=4)
    try:
        analysis, u1 = llm.chat_json(system, p1, schema=SCHEMA1)
    except (ValueError, RuntimeError) as e:
        progress(jid, stage='실패', done=True,
                 error='분석 응답이 JSON이 아니다: ' + str(e)[:200],
                 raw=llm.LAST_RAW['text'][:4000])
        raise
    progress(jid, analysis=analysis, usage_analyze=u1)

    # 갱신 대상 페이지 전문을 붙인다 — 없으면 모델이 기존 내용을 지운다
    tgt = []
    for t in (analysis.get('update_targets') or [])[:5]:
        fp = os.path.join(ROOT, 'wiki', t.get('page', '') + '.md')
        if os.path.exists(fp):
            tgt.append('\n### %s\n```\n%s\n```' % (t['page'], rd(fp)))
    targets = ''.join(tgt) or '(갱신 대상 없음)'

    progress(jid, stage='작성', step=3, of=4)
    p2 = STEP2 % {'path': rel, 'raw': raw_text,
                  'analysis': json.dumps(analysis, ensure_ascii=False, indent=2),
                  'targets': targets, 'actions': ' / '.join(ACTIONS),
                  'marker': marker, 'today': today}
    try:
        plan, u2 = llm.chat_json(system, p2, max_tokens=32000, schema=SCHEMA2)
    except (ValueError, RuntimeError) as e:
        progress(jid, stage='실패', done=True,
                 error='편집안 응답이 JSON이 아니다: ' + str(e)[:200],
                 raw=llm.LAST_RAW['text'][:4000])
        raise
    progress(jid, plan=plan, usage_write=u2)

    if plan_only:
        progress(jid, stage='계획만', done=True)
        return {'jid': jid, 'analysis': analysis, 'plan': plan, 'applied': []}

    progress(jid, stage='마무리', step=4, of=4)
    applied = apply_plan(plan, rel, analysis)
    progress(jid, stage='완료', done=True, applied=applied)
    return {'jid': jid, 'analysis': analysis, 'plan': plan, 'applied': applied}


def apply_plan(plan, rel, analysis):
    """편집안을 파일로 쓴다. **`raw/` 본문은 절대 건드리지 않는다.**"""
    applied = []
    today = datetime.date.today().isoformat()

    for e in plan.get('edits') or []:
        name = (e.get('page') or '').strip()
        content = e.get('content') or ''
        if not name or not content.startswith('---'):
            continue  # frontmatter 없는 것은 형식 위반이라 버린다
        fp = os.path.join(ROOT, 'wiki', name + '.md')
        with io.open(fp, 'w', encoding='utf-8', newline='\n') as f:
            f.write(content if content.endswith('\n') else content + '\n')
        applied.append({'page': name, 'mode': e.get('mode'), 'why': e.get('why')})

    # 리뷰 큐 — 인제스트를 막지 않고 쌓아둔다
    rv = [r for r in (plan.get('review') or []) if r.get('action') in ACTIONS]
    if rv:
        head = ''
        if not os.path.exists(REVIEW):
            head = ('---\ntitle: 리뷰 큐\ntype: reference\nstatus: draft\n'
                    'updated: %s\ntags: [meta]\n---\n\n'
                    '# 리뷰 큐\n\n자동 인제스트가 **판단을 미룬 것들.** '
                    '처리하면 줄을 지우지 말고 `- [x]`로 바꾼다.\n' % today)
        with io.open(REVIEW, 'a', encoding='utf-8', newline='\n') as f:
            if head:
                f.write(head)
            f.write('\n## %s — `%s`\n' % (today, rel))
            for r in rv:
                f.write('- [ ] **%s** · %s — %s\n' % (
                    r['action'], r.get('subject', ''), r.get('detail', '')))
        applied.append({'review': len(rv)})

    # raw는 ingested 한 줄만 바꾼다. 본문·서지정보는 불변이다
    src = os.path.join(ROOT, 'raw', '') and os.path.join(ROOT, rel)
    t = rd(src)
    if re.search(r'^ingested:\s*false', t, re.M):
        t = re.sub(r'^ingested:\s*false', 'ingested: true', t, count=1, flags=re.M)
        with io.open(src, 'w', encoding='utf-8', newline='\n') as f:
            f.write(t)
        applied.append({'raw': rel, 'ingested': True})

    line = plan.get('log') or ('인제스트 — ' + rel)
    with io.open(os.path.join(ROOT, 'wiki', 'log.md'), 'a',
                 encoding='utf-8', newline='\n') as f:
        f.write('%s | ingest | %s | %s\n' % (today, rel, line))
    return applied


def apply_saved(jid):
    """이미 만들어 둔 계획을 그대로 적용한다.

    `--plan-only` 로 계획을 보고 확인한 뒤 적용하는 흐름이다.
    다시 돌리면 호출 값이 또 나가고 계획이 달라질 수 있다 —
    **확인한 계획과 적용한 계획이 같아야 한다.**
    """
    f = os.path.join(REPORTS, 'ingest-%s.json' % jid)
    if not os.path.exists(f):
        raise SystemExit('없는 작업: ' + jid)
    d = json.loads(rd(f))
    if not d.get('plan'):
        raise SystemExit('이 작업에는 계획이 없다 (단계: %s)' % d.get('stage'))
    if d.get('applied'):
        raise SystemExit('이미 적용됐다: ' + json.dumps(d['applied'], ensure_ascii=False))
    applied = apply_plan(d['plan'], d['path'], d.get('analysis') or {})
    progress(jid, stage='완료', done=True, applied=applied)
    return applied


def latest_jid():
    fs = sorted(glob.glob(os.path.join(REPORTS, 'ingest-*.json')),
                key=os.path.getmtime)
    return os.path.basename(fs[-1])[7:-5] if fs else None


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')  # 윈도우 콘솔은 기본이 cp949다
    except AttributeError:
        pass
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    flags = set(a for a in sys.argv[1:] if a.startswith('--'))
    if '--apply' in flags:
        jid = args[0] if args else latest_jid()
        print(json.dumps(apply_saved(jid), ensure_ascii=False, indent=2))
    elif not args:
        q = pending()
        s = llm.status()
        print('LLM  %s' % ('준비됨 · ' + s.get('model', '') if s['ok'] else '없음 — ' + s['why']))
        print('대기 %d건' % len(q))
        for r in q:
            print('  %-52s %s %dB' % (r['path'], r['axis'] or '?', r['bytes']))
        if not q:
            print('  (없음)')
    else:
        r = run(args[0], dry='--dry-run' in flags, plan_only='--plan-only' in flags)
        print(json.dumps(r, ensure_ascii=False, indent=2)[:3000])
