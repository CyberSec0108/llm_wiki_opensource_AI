// 위키 탭 목록: 제목이 두 줄로 흐르지 않고 … 로 잘리는지,
// 목록 폭 손잡이가 배선됐는지 확인한다.
const { ctx, doc, registry, findAllIn } = require('./harness');

const LONG = '(AI보호) AI 모델 통제 이탈 사례';

function check(label) {
  const names = findAllIn(registry.plist, '.item-name');
  const heads = findAllIn(registry.plist, '.item-head');
  // 인라인 style 로 flex 를 걸면 CSS 의 자르기 규칙이 안 먹는다
  const inline = !!(heads[0] && heads[0].attrs.style);
  console.log(label, '| 제목 span', names.length, '| 머리 행', heads.length,
              '| 툴팁', JSON.stringify(names[0] && names[0].title),
              '| 인라인 style 잔재', inline);
  return names.length === 1 && heads.length === 1 && !inline &&
         names[0].title === LONG;
}

(async () => {
  try {
    // 검색 결과와 전체 목록은 각각 따로 그린다 — 둘 다 본다
    ctx.drawList([{ name: LONG, layer: 'wiki', path: 'wiki/a.md',
                    folder: 'wiki', openable: true }]);
    const a = check('검색 결과');

    // PAGES 는 스크립트 스코프의 let 이라 밖에서 못 넣는다 — 실제 경로로 채운다
    ctx.fetch = () => Promise.resolve({ json: () => Promise.resolve(
      [{ name: LONG, layer: 'wiki', path: 'wiki/a.md',
         axis: 'securing-ai', sub: '요약' }]) });
    await ctx.loadWiki();
    const b = check('전체 목록');

    if (a && b) console.log('==> 목록 제목이 한 줄로 잘린다  OK');
    else { console.log('==> 제목이 안 잘린다  실패'); process.exit(1); }

    // 끌기 자체는 가짜 DOM 에서 재현할 수 없다.
    // 손잡이가 배선됐는지와 기본값 되돌리기만 본다.
    const hd = registry.splitDrag;
    const sp = doc.querySelector('.split');
    console.log('손잡이 있나:', !!hd, '| 두 번 누르기 배선:', typeof hd.ondblclick);
    if (typeof hd.ondblclick !== 'function') {
      console.log('==> 손잡이가 배선되지 않았다  실패'); process.exit(1); }
    hd.ondblclick();
    const w = sp.style.getPropertyValue('--splitw');
    console.log('두 번 누른 뒤 폭:', JSON.stringify(w));
    if (w !== '300px') { console.log('==> 기본값 복귀 실패'); process.exit(1); }
    console.log('==> 폭 조절 손잡이 OK');
  } catch (e) {
    console.log('처리 오류:', e.message);
    console.log(e.stack.split('\n').slice(1, 3).join('\n'));
    process.exit(1);
  }
})();
