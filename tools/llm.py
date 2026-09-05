"""LLM 호출 계층 — 제공자를 아는 유일한 파일.

`ingest.py`는 이 파일만 부른다. 제공자를 바꿔도 파이프라인은 그대로다.

**설정은 볼트 루트의 `.env` 한 곳에 있다.** 키·제공자·모델을 전부 거기서 바꾼다.
설정이 두 곳에 있으면 어느 쪽이 이겼는지 알 수 없게 된다 — 이 볼트에서
반복해서 문제가 됐던 실패 방식이다.

`.env`는 `.gitignore`에 있다. 키가 커밋되면 되돌릴 수 없다.
"""

import io
import json
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = os.path.join(ROOT, '.env')

DEFAULT = {
    'LLM_PROVIDER': 'openrouter',
    'LLM_MODEL': 'anthropic/claude-sonnet-4.5',
    'LLM_MAX_TOKENS': '8000',
    'LLM_TEMPERATURE': '0',
    'LLM_TIMEOUT': '300',
    # 추론 모델이 답을 쓰기 전에 얼마나 오래 생각할지. low 로 시작한다 —
    # 실측에서 기본값은 첫 답변 토큰까지 47초를 썼다.
    # low | medium | high | none(생각 끄기)
    'LLM_REASONING': 'low',
    'LLM_FIRST_TOKEN_TIMEOUT': '180',
}

# 제공자별로 필요한 것. 키 이름을 코드 여기저기 흩지 않는다.
PROVIDERS = {
    'openrouter': {
        'env': 'OPENROUTER_API_KEY',
        'base_url': 'https://openrouter.ai/api/v1',
        'sdk': 'openai',
        'signup': 'https://openrouter.ai/keys',
        'models': 'https://openrouter.ai/models',
    },
    'anthropic': {
        'env': 'ANTHROPIC_API_KEY',
        'base_url': None,
        'sdk': 'anthropic',
        'signup': 'https://console.anthropic.com/settings/keys',
        'models': 'https://docs.anthropic.com/en/docs/about-claude/models',
    },
}

TEMPLATE = """# LLM Wiki 설정 — 이 파일 하나가 정본이다.
# .gitignore에 있으므로 커밋되지 않는다. 키를 여기 둬도 안전하다.

# 제공자: openrouter | anthropic
LLM_PROVIDER=openrouter

# 모델. OpenRouter는 키 하나로 여러 모델을 쓴다.
#   anthropic/claude-sonnet-4.5   균형 (기본)
#   anthropic/claude-opus-4.1     더 정확, 더 비쌈
#   google/gemini-2.5-pro         긴 문서에 강함
#   deepseek/deepseek-chat        저렴
# 목록: https://openrouter.ai/models
LLM_MODEL=anthropic/claude-sonnet-4.5

# 한 번에 받을 최대 출력 토큰
LLM_MAX_TOKENS=8000
LLM_TEMPERATURE=0

# ── 키 ── 쓰는 제공자의 것만 채우면 된다
OPENROUTER_API_KEY=
ANTHROPIC_API_KEY=
"""


def parse_env(text):
    """KEY=VALUE 만 읽는다. 따옴표와 주석을 벗긴다."""
    d = {}
    for line in text.split('\n'):
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        v = v.split(' #')[0].strip().strip('"').strip("'")
        d[k.strip()] = v
    return d


def read_env():
    if not os.path.exists(ENV):
        return {}
    try:
        return parse_env(io.open(ENV, encoding='utf-8').read())
    except OSError:
        return {}


def ensure_env():
    """없으면 주석 달린 템플릿을 만들어 준다. 사용자가 열어서 채우면 된다."""
    if not os.path.exists(ENV):
        io.open(ENV, 'w', encoding='utf-8', newline='\n').write(TEMPLATE)
        return True
    return False


def get(key, default=''):
    """진짜 환경변수가 이긴다. 없으면 .env, 없으면 기본값.

    환경변수를 이기게 두는 이유: 서버를 다른 방식으로 띄울 때(CI, 컨테이너)
    파일을 고치지 않고 덮어쓸 수 있어야 한다.
    """
    v = os.environ.get(key)
    if v:
        return v
    return read_env().get(key) or DEFAULT.get(key, default)


def source_of(key):
    if os.environ.get(key):
        return '환경변수'
    if read_env().get(key):
        return '.env'
    return '기본값'


def load_config():
    return {
        'provider': get('LLM_PROVIDER'),
        'model': get('LLM_MODEL'),
        'max_tokens': int(get('LLM_MAX_TOKENS') or 8000),
        'temperature': float(get('LLM_TEMPERATURE') or 0),
        'timeout': float(get('LLM_TIMEOUT') or 300),
        'reasoning': (get('LLM_REASONING') or 'low').strip().lower(),
    }


def reasoning_body(c):
    """OpenRouter 의 추론 조절 파라미터. 모르는 값이면 아무것도 안 보낸다.

    `none` 이면 생각 자체를 끈다 — 가장 빠르지만 답변 품질이 떨어질 수 있다.
    추론을 지원하지 않는 모델은 이 파라미터를 그냥 무시한다.
    """
    r = c.get('reasoning') or ''
    if r in ('low', 'medium', 'high'):
        return {'reasoning': {'effort': r}}
    if r in ('none', 'off', 'exclude'):
        return {'reasoning': {'exclude': True}}
    return {}


def save_config(**kw):
    """`.env`의 해당 줄만 갈아끼운다. 주석과 나머지 줄은 그대로 둔다."""
    ensure_env()
    text = io.open(ENV, encoding='utf-8').read()
    m = {'provider': 'LLM_PROVIDER', 'model': 'LLM_MODEL',
         'max_tokens': 'LLM_MAX_TOKENS', 'temperature': 'LLM_TEMPERATURE',
         'key': None}
    for k, v in kw.items():
        if v is None or v == '':
            continue
        name = m.get(k, k)
        if k == 'key':  # 지금 제공자의 키 칸에 넣는다
            name = PROVIDERS[get('LLM_PROVIDER')]['env']
        lines, hit = text.split('\n'), False
        for i, ln in enumerate(lines):
            if ln.strip().startswith(name + '='):
                lines[i] = name + '=' + str(v)
                hit = True
                break
        if not hit:
            lines.append(name + '=' + str(v))
        text = '\n'.join(lines)
    io.open(ENV, 'w', encoding='utf-8', newline='\n').write(text)
    return load_config()


def api_key(provider=None):
    p = PROVIDERS[provider or get('LLM_PROVIDER')]
    return get(p['env'])


def status():
    """지금 호출이 가능한가. UI가 이걸 보고 버튼을 켠다."""
    c = load_config()
    p = PROVIDERS.get(c['provider'])
    base = {'config': c, 'env_path': ENV, 'env_exists': os.path.exists(ENV),
            'providers': sorted(PROVIDERS)}
    if not p:
        return dict(base, ok=False, why='모르는 제공자: ' + str(c['provider']))
    key = api_key(c['provider'])
    base.update({'env': p['env'], 'signup': p['signup'], 'models': p['models'],
                 'from': source_of(p['env'])})
    if not key:
        return dict(base, ok=False, why=p['env'] + ' 가 비어 있다')
    try:
        __import__(p['sdk'])
    except ImportError:
        return dict(base, ok=False, why='pip install ' + p['sdk'])
    return dict(base, ok=True, provider=c['provider'], model=c['model'],
                key_tail='...' + key[-4:])


def chat(system, user, max_tokens=None, cache_system=True, schema=None):
    """한 번 호출하고 텍스트를 돌려준다.

    `system`에는 규칙 문서가 통째로 들어간다 — 매 호출 같은 내용이므로
    캐시가 걸리면 값이 크게 싸진다. 그래서 규칙은 system, 자료는 user에 둔다.
    """
    c = load_config()
    p = PROVIDERS[c['provider']]
    key = api_key(c['provider'])
    if not key:
        raise RuntimeError(p['env'] + ' 가 비어 있다. ' + ENV + ' 를 열어 채워라. '
                           '키 발급: ' + p['signup'])
    mt = max_tokens or c['max_tokens']

    if p['sdk'] == 'anthropic':
        import anthropic
        cl = anthropic.Anthropic(api_key=key, timeout=c['timeout'])
        sys_blocks = [{'type': 'text', 'text': system}]
        if cache_system:
            sys_blocks[0]['cache_control'] = {'type': 'ephemeral'}
        r = cl.messages.create(
            model=c['model'], max_tokens=mt,
            system=sys_blocks,
            messages=[{'role': 'user', 'content': user}],
        )
        text = ''.join(b.text for b in r.content if b.type == 'text')
        u = r.usage
        return text, {'in': u.input_tokens, 'out': u.output_tokens,
                      'cache_read': getattr(u, 'cache_read_input_tokens', 0)}

    # OpenRouter — OpenAI 호환 스펙
    from openai import OpenAI
    cl = OpenAI(base_url=p['base_url'], api_key=key,
                timeout=c['timeout'], max_retries=1)
    # 스키마 호출에는 추론 조절을 걸지 않는다. 실측에서 effort 를 명시하면
    # 오히려 추론이 늘었다 — 간단한 스키마 호출은 미설정이 추론 토큰 1개인데
    # low 는 206개였다(effort 가 최소 예산을 깐다). 모델이 알아서 하게 둔다.
    # 조절이 필요한 건 답변을 길게 쓰는 스트리밍 호출뿐이다.
    kw = dict(
        model=c['model'], max_tokens=mt, temperature=c['temperature'],
        messages=[{'role': 'system', 'content': system},
                  {'role': 'user', 'content': user}],
        extra_headers={'HTTP-Referer': 'https://github.com/CyberSec0108/llm_wiki_opensource_AI',
                       'X-Title': 'LLM Wiki'},
    )
    # JSON 강제. 이게 걸리면 형식 위반이 사라져서 싼 모델도 쓸 만해진다.
    # 지원하지 않는 모델이 있으므로 실패하면 그냥 다시 부른다.
    # 스키마를 주면 형식이 강제된다. `json_object` 모드는 쓰지 않는다 —
    # 실측에서 glm-5.3-flash 가 그 모드에서 JSON 대신 산문을 뱉었다.
    if schema:
        sk = dict(kw, response_format={
            'type': 'json_schema',
            'json_schema': {'name': 'result', 'strict': True, 'schema': schema},
        })
        try:
            return _openai_call(cl, sk)
        except Exception as e:                       # noqa: BLE001
            code = getattr(getattr(e, 'response', None), 'status_code', None)
            # 인증·한도·잔액은 재시도해도 같다. 요금만 두 번 나간다
            if code in (401, 402, 403, 429) or (code and code >= 500):
                raise
            # 일시적 실패면 스키마를 유지한 채 한 번 더. 맨몸으로 내려가지 않는다 —
            # 스키마 없는 호출은 YAML이나 빈 응답을 내놓고, 그게 조용히 흘러가서
            # 실제로 "제공된 텍스트가 없습니다" 같은 가짜 분석 결과를 만들어냈다.
            return _openai_call(cl, sk)
    return _openai_call(cl, kw)


def chat_stream(system, user, max_tokens=None, on_delta=None, cancel=None,
                cache_system=True, on_reasoning=None):
    """토큰 단위로 스트리밍한다. **스키마를 쓰지 않는다** — 순수 텍스트만.

    JSON 스키마와 스트리밍은 같이 못 쓴다. 완성되기 전 JSON은 파싱할 수 없어서
    부분 문자열을 화면에 보여줄 방법이 없기 때문이다. 그래서 질문 탭은
    답변 본문은 이 함수로 스트리밍하고, 출처·판단(in_wiki 등)은 답변이 끝난
    뒤 짧은 스키마 호출로 따로 뽑는다 (`tools/query.py`의 EXTRACT 단계).

    `cancel()`이 True를 돌려주면 그 자리에서 스트림을 끊는다 — 클라이언트가
    끊었다고 표시만 하는 게 아니라 **실제로 연결을 닫아 과금을 멈춘다.**

    반환: (전체 텍스트, usage, 중단 여부)
    """
    on_delta = on_delta or (lambda d: None)
    on_reasoning = on_reasoning or (lambda d: None)
    cancel = cancel or (lambda: False)
    c = load_config()
    p = PROVIDERS[c['provider']]
    key = api_key(c['provider'])
    if not key:
        raise RuntimeError(p['env'] + ' 가 비어 있다. ' + ENV + ' 를 열어 채워라. '
                           '키 발급: ' + p['signup'])
    mt = max_tokens or c['max_tokens']
    parts, cancelled = [], False

    if p['sdk'] == 'anthropic':
        import anthropic
        cl = anthropic.Anthropic(api_key=key, timeout=c['timeout'])
        sys_blocks = [{'type': 'text', 'text': system}]
        if cache_system:
            sys_blocks[0]['cache_control'] = {'type': 'ephemeral'}
        with cl.messages.stream(model=c['model'], max_tokens=mt,
                                system=sys_blocks,
                                messages=[{'role': 'user', 'content': user}]) as stream:
            for delta in stream.text_stream:
                if cancel():
                    cancelled = True
                    break
                parts.append(delta)
                on_delta(delta)
            if cancelled:
                return ''.join(parts), {'in': 0, 'out': 0, 'cache_read': 0}, True
            final = stream.get_final_message()
            u = final.usage
            return ''.join(parts), {'in': u.input_tokens, 'out': u.output_tokens,
                                    'cache_read': getattr(u, 'cache_read_input_tokens', 0)}, False

    # OpenRouter — OpenAI 호환 스펙
    from openai import OpenAI
    cl = OpenAI(base_url=p['base_url'], api_key=key,
                timeout=c['timeout'], max_retries=1)
    stream = cl.chat.completions.create(
        model=c['model'], max_tokens=mt, temperature=c['temperature'],
        messages=[{'role': 'system', 'content': system},
                  {'role': 'user', 'content': user}],
        stream=True, stream_options={'include_usage': True},
        extra_body=reasoning_body(c),
        extra_headers={'HTTP-Referer': 'https://github.com/CyberSec0108/llm_wiki_opensource_AI',
                       'X-Title': 'LLM Wiki'},
    )
    usage = {'in': 0, 'out': 0, 'cache_read': 0}
    # 추론 모델은 답을 쓰기 전에 오래 "생각"만 한다 — 그동안 토큰이 하나도
    # 안 온다. 실측에서 340초가 지나도록 첫 토큰이 없는데 SDK 타임아웃도
    # 걸리지 않았다(스트리밍 응답은 연결이 열려 있는 한 read timeout 이
    # 안 걸린다). 무한 대기를 막으려면 우리가 직접 시계를 봐야 한다.
    first_wait = float(get('LLM_FIRST_TOKEN_TIMEOUT') or 180)
    t0 = time.monotonic()
    try:
        for chunk in stream:
            if cancel():
                cancelled = True
                break
            if not parts and time.monotonic() - t0 > first_wait:
                raise RuntimeError(
                    '%d초 동안 첫 토큰이 오지 않았다. 모델이 생각만 하고 있다 — '
                    '.env 의 LLM_MODEL 을 더 빠른 모델로 바꾸거나 '
                    'LLM_FIRST_TOKEN_TIMEOUT 을 늘려라.' % first_wait)
            if chunk.choices and chunk.choices[0].delta:
                dl = chunk.choices[0].delta
                # 추론 모델은 답을 쓰기 전 생각을 delta.reasoning 으로 흘려보낸다.
                # 실측: glm-5.3-flash 는 첫 답변 토큰까지 47초 동안 청크 1,437개를
                # 전부 reasoning 으로 보냈다. 이걸 버리면 화면이 47초간 멈춘 것처럼
                # 보이므로, 그대로 넘겨서 "생각 중" 상자에 보여준다.
                rz = getattr(dl, 'reasoning', None)
                if rz:
                    on_reasoning(rz)
                if dl.content:
                    d = dl.content
                    parts.append(d)
                    on_delta(d)
            if getattr(chunk, 'usage', None):
                u = chunk.usage
                usage = {'in': u.prompt_tokens, 'out': u.completion_tokens, 'cache_read': 0}
    finally:
        # 클라이언트가 끊었으면 연결도 닫는다 — 안 그러면 서버가 계속 생성하고
        # 계속 과금된다. "중단"이 실제로 멈추는 게 아니라 화면만 멈추면 안 된다.
        try:
            stream.close()
        except Exception:                             # noqa: BLE001
            pass
    return ''.join(parts), usage, cancelled


def _openai_call(cl, kw):
    r = cl.chat.completions.create(**kw)
    u = getattr(r, 'usage', None)
    return r.choices[0].message.content or '', {
        'in': getattr(u, 'prompt_tokens', 0) if u else 0,
        'out': getattr(u, 'completion_tokens', 0) if u else 0,
        'cache_read': 0,
    }


def ping():
    """키가 실제로 통하는지 최소 비용으로 확인한다.

    `status()`는 키가 **있는지**만 본다 — 만료·잔액부족·오타는 못 잡는다.
    실제로 한 번 불러봐야 알 수 있고, 그걸 파이프라인 중간에 알면 늦다.
    """
    try:
        text, u = chat('Reply with OK.', 'ping', max_tokens=5, cache_system=False)
        return {'ok': True, 'reply': (text or '').strip()[:40], 'usage': u,
                'model': load_config()['model']}
    except Exception as e:                           # noqa: BLE001
        msg = str(e)
        code = getattr(getattr(e, 'response', None), 'status_code', None)
        hint = {401: '키가 만료됐거나 잘못됐다. 새로 발급받아라',
                402: '잔액이 부족하다. 크레딧을 채워라',
                403: '이 모델에 접근 권한이 없다',
                404: '모델 이름이 틀렸다',
                429: '요청 한도를 넘었다. 잠시 뒤 다시'}.get(code, '')
        return {'ok': False, 'code': code, 'why': hint or msg[:300],
                'detail': msg[:500], 'model': load_config()['model'],
                'signup': PROVIDERS[get('LLM_PROVIDER')]['signup']}


def _unfence(text):
    """```json 울타리와 앞뒤 잡담을 벗긴다."""
    t = (text or '').strip()
    if t.startswith('```'):
        t = t.split('\n', 1)[1] if '\n' in t else t
        if t.rstrip().endswith('```'):
            t = t.rstrip()[:-3]
    t = t.strip()
    if not t.startswith('{') and '{' in t:
        t = t[t.find('{'):t.rfind('}') + 1]
    return t


LAST_RAW = {'text': ''}   # 파싱이 깨졌을 때 무엇이 왔는지 보려고 남긴다


def chat_json(system, user, max_tokens=None, schema=None):
    """JSON을 기대하는 호출.

    싼 모델일수록 형식을 흘린다. 세 겹으로 막는다.
      1. 스키마를 주면 모델이 형식을 어길 수 없다
      2. 울타리·잡담을 벗긴다
      3. 그래도 깨지면 **받은 텍스트를 되돌려주며 JSON만 다시 달라고 한다**
    """
    text, usage = chat(system, user, max_tokens, schema=schema)
    LAST_RAW['text'] = text
    if not (text or '').strip():
        raise RuntimeError(
            '모델이 빈 응답을 돌려줬다 (max_tokens=%s). 늘리거나 모델을 바꿔라 — '
            '추론 모델은 추론 토큰이 max_tokens 를 먹는다.'
            % (max_tokens or load_config()['max_tokens']))
    try:
        return json.loads(_unfence(text)), usage
    except ValueError:
        pass
    # 복구 — 앞선 답을 그대로 보여주고 JSON만 뽑아 달라고 한다
    fix, u2 = chat(
        'JSON만 출력한다. 설명·인사·코드블록 울타리를 붙이지 않는다.',
        '아래 텍스트에서 JSON 객체만 그대로 뽑아 출력하라. 내용을 바꾸지 마라.\n\n'
        + (text or '')[:60000],
        max_tokens, cache_system=False, schema=schema)
    LAST_RAW['text'] = fix
    if not (fix or '').strip():
        raise RuntimeError('복구 시도도 빈 응답이다. 원문: ' + (text or '')[:200])
    usage = {k: usage.get(k, 0) + u2.get(k, 0) for k in set(usage) | set(u2)}
    return json.loads(_unfence(fix)), usage


if __name__ == '__main__':
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
    if ensure_env():
        print('설정 파일을 만들었다: ' + ENV)
        print('열어서 키를 채워라.')
    if len(sys.argv) > 1 and sys.argv[1] == 'test':
        print(json.dumps(ping(), ensure_ascii=False, indent=2))
        sys.exit(0 if ping()['ok'] else 1)
    if len(sys.argv) > 1 and sys.argv[1] == 'set':
        # python tools/llm.py set provider=openrouter model=openai/gpt-4o
        kw = dict(a.split('=', 1) for a in sys.argv[2:] if '=' in a)
        save_config(**kw)
    s = status()
    print(json.dumps(s, ensure_ascii=False, indent=2))
    if not s['ok']:
        sys.exit(1)
