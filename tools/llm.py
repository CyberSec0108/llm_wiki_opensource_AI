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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = os.path.join(ROOT, '.env')

DEFAULT = {
    'LLM_PROVIDER': 'openrouter',
    'LLM_MODEL': 'anthropic/claude-sonnet-4.5',
    'LLM_MAX_TOKENS': '8000',
    'LLM_TEMPERATURE': '0',
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
    }


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


def chat(system, user, max_tokens=None, cache_system=True, want_json=False):
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
        cl = anthropic.Anthropic(api_key=key)
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
    cl = OpenAI(base_url=p['base_url'], api_key=key)
    kw = dict(
        model=c['model'], max_tokens=mt, temperature=c['temperature'],
        messages=[{'role': 'system', 'content': system},
                  {'role': 'user', 'content': user}],
        extra_headers={'HTTP-Referer': 'https://github.com/CyberSec0108/llm_wiki_opensource_AI',
                       'X-Title': 'LLM Wiki'},
    )
    # JSON 강제. 이게 걸리면 형식 위반이 사라져서 싼 모델도 쓸 만해진다.
    # 지원하지 않는 모델이 있으므로 실패하면 그냥 다시 부른다.
    if want_json:
        try:
            return _openai_call(cl, dict(kw, response_format={'type': 'json_object'}))
        except Exception:                            # noqa: BLE001
            pass
    return _openai_call(cl, kw)


def _openai_call(cl, kw):
    r = cl.chat.completions.create(**kw)
    u = getattr(r, 'usage', None)
    return r.choices[0].message.content or '', {
        'in': getattr(u, 'prompt_tokens', 0) if u else 0,
        'out': getattr(u, 'completion_tokens', 0) if u else 0,
        'cache_read': 0,
    }


def chat_json(system, user, max_tokens=None):
    """JSON을 기대하는 호출. 코드블록 울타리를 벗겨준다.

    모델이 ```json 으로 감싸는 일이 잦다. 파이프라인이 매번 처리하지 않도록
    여기서 한 번만 벗긴다.
    """
    text, usage = chat(system, user, max_tokens, want_json=True)
    t = text.strip()
    if t.startswith('```'):
        t = t.split('\n', 1)[1] if '\n' in t else t
        if t.rstrip().endswith('```'):
            t = t.rstrip()[:-3]
    t = t.strip()
    # 앞뒤 잡담을 흘리는 모델 대비 — 첫 { 부터 마지막 } 까지
    if not t.startswith('{') and '{' in t:
        t = t[t.find('{'):t.rfind('}') + 1]
    return json.loads(t), usage


if __name__ == '__main__':
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
    if ensure_env():
        print('설정 파일을 만들었다: ' + ENV)
        print('열어서 키를 채워라.')
    if len(sys.argv) > 1 and sys.argv[1] == 'set':
        # python tools/llm.py set provider=openrouter model=openai/gpt-4o
        kw = dict(a.split('=', 1) for a in sys.argv[2:] if '=' in a)
        save_config(**kw)
    s = status()
    print(json.dumps(s, ensure_ascii=False, indent=2))
    if not s['ok']:
        sys.exit(1)
