"""LLM 호출 계층 — 제공자를 아는 유일한 파일.

`ingest.py`는 이 파일만 부른다. 제공자를 바꿔도 파이프라인은 그대로다.

**키는 환경변수에서만 읽는다.** 볼트 어디에도 저장하지 않는다 —
볼트는 git에 올라가고, 키가 섞이면 되돌릴 수 없다.

설정(제공자·모델)은 `tools/llm.json`에 둔다. 이건 비밀이 아니라서 커밋해도 된다.
"""

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONF = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'llm.json')

DEFAULT = {
    'provider': 'openrouter',
    'model': 'anthropic/claude-sonnet-4.5',
    'max_tokens': 8000,
    'temperature': 0,
}

# 제공자별로 필요한 것. 키 이름을 코드 여기저기 흩지 않는다.
PROVIDERS = {
    'openrouter': {
        'env': 'OPENROUTER_API_KEY',
        'base_url': 'https://openrouter.ai/api/v1',
        'sdk': 'openai',
        'signup': 'https://openrouter.ai/keys',
    },
    'anthropic': {
        'env': 'ANTHROPIC_API_KEY',
        'base_url': None,
        'sdk': 'anthropic',
        'signup': 'https://console.anthropic.com/settings/keys',
    },
}


def load_config():
    c = dict(DEFAULT)
    if os.path.exists(CONF):
        try:
            with open(CONF, encoding='utf-8') as f:
                c.update(json.load(f))
        except (ValueError, OSError):
            pass  # 설정이 깨졌으면 기본값으로 간다. 인제스트를 막지 않는다
    return c


def save_config(**kw):
    c = load_config()
    c.update({k: v for k, v in kw.items() if v is not None})
    with open(CONF, 'w', encoding='utf-8') as f:
        json.dump(c, f, ensure_ascii=False, indent=2)
    return c


def status():
    """지금 호출이 가능한가. UI가 이걸 보고 버튼을 켠다."""
    c = load_config()
    p = PROVIDERS.get(c['provider'])
    if not p:
        return {'ok': False, 'why': '모르는 제공자: ' + str(c['provider']), 'config': c}
    key = os.environ.get(p['env'], '')
    if not key:
        return {'ok': False, 'why': p['env'] + ' 환경변수가 없다',
                'env': p['env'], 'signup': p['signup'], 'config': c}
    try:
        __import__(p['sdk'])
    except ImportError:
        return {'ok': False, 'why': 'pip install ' + p['sdk'], 'config': c}
    return {'ok': True, 'provider': c['provider'], 'model': c['model'],
            'key_tail': '...' + key[-4:], 'config': c}


def chat(system, user, max_tokens=None, cache_system=True):
    """한 번 호출하고 텍스트를 돌려준다.

    `system`에는 규칙 문서가 통째로 들어간다 — 매 호출 같은 내용이므로
    캐시가 걸리면 값이 크게 싸진다. 그래서 규칙은 system, 자료는 user에 둔다.
    """
    c = load_config()
    p = PROVIDERS[c['provider']]
    key = os.environ.get(p['env'])
    if not key:
        raise RuntimeError(p['env'] + ' 가 없다. ' + p['signup'] + ' 에서 발급받아 설정하라')
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
    r = cl.chat.completions.create(
        model=c['model'], max_tokens=mt, temperature=c['temperature'],
        messages=[{'role': 'system', 'content': system},
                  {'role': 'user', 'content': user}],
        extra_headers={'HTTP-Referer': 'https://github.com/CyberSec0108/llm_wiki_opensource_AI',
                       'X-Title': 'LLM Wiki'},
    )
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
    text, usage = chat(system, user, max_tokens)
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
    if len(sys.argv) > 1 and sys.argv[1] == 'set':
        # python tools/llm.py set provider=openrouter model=anthropic/claude-sonnet-4.5
        kw = dict(a.split('=', 1) for a in sys.argv[2:] if '=' in a)
        print(json.dumps(save_config(**kw), ensure_ascii=False, indent=2))
    else:
        s = status()
        print(json.dumps(s, ensure_ascii=False, indent=2))
        if not s['ok']:
            sys.exit(1)
