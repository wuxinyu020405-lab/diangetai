// sign_runner.js: 接收 md5，跑 sign.js 的 getSign，把 X-Bogus 写 stdout
const fs = require('fs');
const path = require('path');
const md5 = process.argv[2];
if (!md5) { console.error('usage: node sign_runner.js <md5>'); process.exit(2); }
const src = fs.readFileSync(path.join(__dirname, 'sign.js'), 'utf8');
const wrapped = "(function(){\n" + src + "\n;return getSign({'X-MS-STUB':" + JSON.stringify(md5) + "});\n})()";
try {
  const r = eval(wrapped);
  process.stdout.write((r && r['X-Bogus']) || '');
} catch (e) {
  console.error('签名失败:', e.message);
  process.exit(1);
}
