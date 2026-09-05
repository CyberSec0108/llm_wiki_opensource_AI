// 답변이 실제로 DOM 에 그려지고, 다음 질의가 아래로 쌓이는지 확인한다.
const { ctx, doc, registry, listeners, fire, findAllIn } = require('./harness');

(async () => {
  try {
    registry.qq.value = '보상 해킹이 뭐야?';
    await ctx.startQuery();
    console.log('등록된 이벤트:', Object.keys(listeners).join(', ') || '(없음)');

    fire('stage', { stage: '질문 확인', step: 0, of: 3 });
    fire('candidates', { pages: [{ ordinal: 1, page: '(AI보호) 보상 해킹' }] });
    fire('stage', { stage: '답변 작성', step: 2, of: 3 });
    // 여러 턴을 구분하려고 id 에 턴 번호가 붙는다 — qsteps-1, qanswer-1 …
    console.log('답변작성 단계에서 진행표시 있나:', !!doc.getElementById('qsteps-1'));

    fire('token', { delta: '# 보상 해킹\n\n' });
    fire('token', { delta: '보상 해킹은 규칙은 지키면서[1] 의도와 다른 결과를 내는 것이다.' });

    await new Promise(r => setTimeout(r, 200));   // 렌더러 throttle(75ms) 대기
    const out = registry.qout;
    const text = out.textContent;
    console.log('첫 토큰 뒤 진행표시 남아있나:', !!doc.getElementById('qsteps-1'), '(false 여야 함)');
    console.log('#qout 텍스트:', JSON.stringify(text.slice(0, 80)));

    const ansBox = doc.getElementById('qanswer-1');
    const inner = ansBox && ansBox.children[0];
    const fellBack = inner && inner.attrs && inner.attrs['data-markdown-fallback'];
    console.log('렌더 방식:', fellBack ? '평문 폴백' : '마크다운 렌더');
    console.log('인용 버튼 수:', findAllIn(out, '.ai-citation-ref').length);
    if (!text.includes('보상 해킹은')) { console.log('==> 답변이 안 그려진다  실패'); process.exit(1); }
    console.log('==> 1번째 답변이 DOM 에 그려진다  OK');

    // ── 두 번째 질문: 앞의 대화가 남아 있어야 한다 ──
    fire('done', { answer: '보상 해킹은 규칙은 지키면서[1] 의도와 다른 결과를 내는 것이다.',
                   sources: [{ ordinal: 1, page: '(AI보호) 보상 해킹', status: 'draft',
                               level: 'warn', strength: '검증 필요' }],
                   in_wiki: true, usage: { in: 1, out: 1 } });
    registry.qq.value = '프롬프트 인젝션은?';
    await ctx.startQuery();
    fire('stage', { stage: '답변 작성', step: 2, of: 3 });
    fire('token', { delta: '프롬프트 인젝션은 지시문을 조작하는 공격이다.' });
    await new Promise(r => setTimeout(r, 200));

    const t2 = registry.qout.textContent;
    const keptFirst = t2.includes('보상 해킹은');
    const hasSecond = t2.includes('프롬프트 인젝션은 지시문');
    console.log('1번째 질문 남아있나:', t2.includes('보상 해킹이 뭐야?'));
    console.log('1번째 답변 남아있나:', keptFirst);
    console.log('2번째 답변 있나  :', hasSecond);
    if (keptFirst && hasSecond) console.log('==> 대화가 아래로 쌓인다  OK');
    else { console.log('==> 대화가 안 쌓인다  실패'); process.exit(1); }
  } catch (e) {
    console.log('처리 오류:', e.message);
    console.log(e.stack.split('\n').slice(1, 3).join('\n'));
    process.exit(1);
  }
})();
