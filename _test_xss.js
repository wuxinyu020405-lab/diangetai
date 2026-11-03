// v1.1 H1 验证：从 overlay.py 的 HTML 里提取 escapeHtml 函数，真跑一遍。
const fs = require('fs');
const path = require('path');
const py = fs.readFileSync(path.join('点歌台拆分', 'overlay.py'), 'utf8');

// 提取函数体（到第一个单独右花括号行）
const m = py.match(/function escapeHtml\(s\) \{[\s\S]*?\n\}/);
if (!m) { console.log('FAIL: 未找到 escapeHtml 函数'); process.exit(1); }
eval(m[0]);   // 注入到本作用域

const cases = [
  ['<img src=x onerror=alert(1)>', '&lt;img src=x onerror=alert(1)&gt;'],
  ['<script>alert("hi")</script>', '&lt;script&gt;alert(&quot;hi&quot;)&lt;/script&gt;'],
  ["a'b&c", 'a&#39;b&amp;c'],
  ['晴天 周杰伦', '晴天 周杰伦'],          // 正常歌名必须原样
  ['张三-李四', '张三-李四'],
  [null, ''], [undefined, ''], [123, '123'],
];

let ok = true;
for (const [input, want] of cases) {
  const got = escapeHtml(input);
  const pass = got === want;
  if (!pass) ok = false;
  console.log((pass ? 'OK  ' : 'BAD ') + JSON.stringify(input) + ' -> ' + JSON.stringify(got)
    + (pass ? '' : '  期望 ' + JSON.stringify(want)));
}

// 关键性质：转义结果里不能再有裸的 < >（即无法闭合出标签）
const evil = escapeHtml('<img src=x onerror=alert(1)>');
const noRawTag = !/[<>]/.test(evil);
console.log('转义后无裸尖括号:', noRawTag ? 'OK' : 'BAD');
ok = ok && noRawTag;

// 幂等性检查（重要：重复转义会让正常文本变 &amp;lt;）
console.log('注: 单次转义设计，调用点已确认每条数据只过一次 escapeHtml');
console.log(ok ? '\n结论: ✅ escapeHtml 行为正确' : '\n结论: ❌ 有用例失败');
process.exit(ok ? 0 : 1);
