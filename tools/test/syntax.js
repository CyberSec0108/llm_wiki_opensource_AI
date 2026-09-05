// index.html 안의 인라인 스크립트가 문법적으로 유효한지 검사한다.
// 브라우저를 열어볼 수 없으니, 최소한 파싱은 통과하는지 확인한다.
const fs = require('fs');
const vm = require('vm');

const html = fs.readFileSync(
  'c:/Users/Hala/Desktop/Sec_Obsidian/tools/static/index.html', 'utf8');

const blocks = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)]
  .map(m => m[1]);

console.log('인라인 스크립트 %d개', blocks.length);
let bad = 0;
blocks.forEach((code, i) => {
  try {
    new vm.Script(code, { filename: `inline-${i}.js` });
    console.log('  #%d  %6d자  문법 통과', i, code.length);
  } catch (e) {
    bad++;
    console.log('  #%d  문법 오류: %s', i, e.message);
  }
});

// 렌더러 파일도 확인
try {
  new vm.Script(fs.readFileSync(
    'c:/Users/Hala/Desktop/Sec_Obsidian/tools/static/restricted-markdown.js', 'utf8'));
  console.log('restricted-markdown.js  문법 통과');
} catch (e) {
  bad++;
  console.log('restricted-markdown.js  문법 오류: %s', e.message);
}
process.exit(bad ? 1 : 0);
