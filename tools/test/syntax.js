// 프런트엔드가 최소한 파싱은 되는지 확인한다. 브라우저를 열어볼 수 없어서다.
//
// 예전에는 index.html 의 인라인 <script> 만 봤다. CSS·JS 를 app.css/app.js 로
// 분리한 뒤에는 그 정규식이 테마 토글 8줄밖에 못 잡아 — 검사할 게 없어서
// "통과" 하는 상태였다. 그래서 index.html 이 실제로 부르는 파일을 따라간다.
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const DIR = 'c:/Users/Hala/Desktop/Sec_Obsidian/tools/static/';
const html = fs.readFileSync(DIR + 'index.html', 'utf8');

let bad = 0;
const ok = (label, fn) => {
  try { fn(); console.log('  %s  통과', label); }
  catch (e) { bad++; console.log('  %s  오류: %s', label, e.message); }
};

// 1) index.html 안에 남은 인라인 스크립트
const inline = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)]
  .map(m => m[1]).filter(s => s.trim());
console.log('인라인 스크립트 %d개', inline.length);
inline.forEach((code, i) =>
  ok(`인라인 #${i} (${code.length}자)`, () => new vm.Script(code)));

// 2) index.html 이 <script src> 로 부르는 파일들 — 이름을 여기 적지 않는다.
//    파일이 하나 늘거나 이름이 바뀌어도 검사가 저절로 따라가야 한다.
const srcs = [...html.matchAll(/<script[^>]*\bsrc="([^"]+)"/g)].map(m => m[1]);
console.log('외부 스크립트 %d개', srcs.length);
srcs.forEach(src => {
  const f = path.join(DIR, src.replace(/^.*\/static\//, '').split('?')[0]);
  ok(`${path.basename(f)} (${fs.existsSync(f) ? fs.statSync(f).size : 0}B)`, () => {
    if (!fs.existsSync(f)) throw new Error('index.html 이 부르는데 파일이 없다');
    new vm.Script(fs.readFileSync(f, 'utf8'));
  });
});

// 3) <link rel=stylesheet> — 파싱기가 없으니 존재와 중괄호 균형만 본다
const css = [...html.matchAll(/<link[^>]*\bhref="([^"]+\.css[^"]*)"/g)].map(m => m[1]);
console.log('스타일시트 %d개', css.length);
css.forEach(href => {
  const f = path.join(DIR, href.replace(/^.*\/static\//, '').split('?')[0]);
  ok(path.basename(f), () => {
    if (!fs.existsSync(f)) throw new Error('index.html 이 부르는데 파일이 없다');
    const t = fs.readFileSync(f, 'utf8');
    const open = (t.match(/{/g) || []).length, close = (t.match(/}/g) || []).length;
    if (open !== close) throw new Error(`중괄호가 안 맞는다 { ${open} vs } ${close}`);
    if (/<\/?style/i.test(t)) throw new Error('<style> 태그가 섞여 있다');
  });
});

process.exit(bad ? 1 : 0);
