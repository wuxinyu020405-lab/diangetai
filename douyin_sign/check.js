// check.js — 抖音通道一键自检（包内 node 跑，全程 fetch，无需额外库）
// 四步：ttwid → 房间解析 → sign.js 签名 → 带签名调 feed 接口验证签名是否被服务端接受
// 输出直接对应处置动作。用法：双击 检查抖音.bat
const { execFileSync } = require('child_process');
const crypto = require('crypto');
const path = require('path');

const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36';
const roomArg = (process.argv[2] || '').trim();
if (!roomArg) { console.log('用法: node douyin_sign\\check.js <抖音房间号>'); process.exit(2); }

async function get(url, cookie) {
  const r = await fetch(url, { headers: { 'User-Agent': UA, 'Referer': 'https://live.douyin.com/', ...(cookie ? { Cookie: cookie } : {}) } });
  return r;
}

(async () => {
  console.log('[1/4] 取 ttwid …');
  let ttwid = '';
  const home = await get('https://live.douyin.com/');
  const sc = home.headers.getSetCookie ? home.headers.getSetCookie() : [];
  for (const c of sc) { const m = /ttwid=([^;]+)/.exec(c); if (m) ttwid = m[1]; }
  if (!ttwid) { console.log('❌ 拿不到 ttwid：网络不通或被防火墙拦（先查网络，与签名无关）'); process.exit(1); }

  console.log('[2/4] 签名组件自检（sign.js 能否产出 X-Bogus）…');
  let sig = '';
  try {
    const stub = crypto.createHash('md5').update('live_id=1,aid=6383').digest('hex');
    sig = execFileSync(process.execPath, [path.join(__dirname, 'sign_runner.js'), stub],
      { cwd: __dirname, timeout: 60000 }).toString().trim();
  } catch (e) {
    console.log('❌ sign.js 运行报错：' + String(e.message).slice(0, 100));
    console.log('   → sign.js 缺失/损坏/算法已变。重新获取一份放 douyin_sign\\sign.js');
    process.exit(1);
  }
  if (!sig) { console.log('❌ sign.js 输出为空：签名算法已过期'); console.log('   → 去 https://github.com/saermart/DouyinLiveWebFetcher 拿最新签名 JS 替换 douyin_sign\\sign.js'); process.exit(1); }
  console.log('   签名能出: ' + sig.slice(0, 12) + '…');

  console.log('[3/4] 服务端验签（带 X-Bogus 请求 feed 接口）…');
  const q = 'aid=6383&app_name=douyin_web&live_id=1&device_platform=web&language=zh-CN' +
    '&cookie_enabled=true&screen_width=1920&screen_height=1080&browser_language=zh-CN' +
    '&browser_platform=Win32&browser_name=Chrome&browser_version=126.0.0.0&count=20' +
    '&source=web_live&channel=channel_pc_web';
  const md5 = crypto.createHash('md5').update(q).digest('hex');
  let sig2 = '';
  try { sig2 = execFileSync(process.execPath, [path.join(__dirname, 'sign_runner.js'), md5], { cwd: __dirname, timeout: 60000 }).toString().trim(); } catch (e) {}
  const feedUrl = 'https://live.douyin.com/webcast/feed/?' + q + '&X-Bogus=' + encodeURIComponent(sig2);
  let body = '';
  try { const r = await get(feedUrl, 'ttwid=' + ttwid); body = await r.text(); } catch (e) {
    console.log('❌ feed 请求异常：' + String(e.message).slice(0, 100) + '（网络/代理问题）'); process.exit(1);
  }
  const accepted = body.length > 2000 && /"data"/.test(body);
  if (!accepted) {
    console.log('\n❌ 签名被服务端拒绝（返回 ' + body.length + ' 字节，正常应为房间列表）');
    console.log('   结论：sign.js 已过期，抖音换了签名算法。');
    console.log('   处置（三选一）：');
    console.log('   1) 等点歌台更新包（推荐，作者会跟进）');
    console.log('   2) 去 https://github.com/saermart/DouyinLiveWebFetcher 或');
    console.log('      https://github.com/SoraYjy/DanmuFree 取最新签名 JS 替换 douyin_sign\\sign.js');
    console.log('   3) 期间先用 B 站点歌，抖音通道会自动"未启用"，不影响主功能');
    process.exit(1);
  }

  console.log('[4/4] 房间号有效性 …');
  if (!/^\d{15,25}$/.test(roomArg)) {
    const enter = 'https://live.douyin.com/webcast/room/web/enter/?aid=6383&app_name=douyin_web&live_id=1' +
      '&device_platform=web&language=zh-CN&web_rid=' + roomArg + '&cookie_enabled=true&screen_width=1920' +
      '&screen_height=1080&browser_language=zh-CN&browser_platform=Win32&browser_name=Chrome&browser_version=126.0.0.0';
    const j = JSON.parse(await (await get(enter, 'ttwid=' + ttwid)).text());
    const room = ((j.data || {}).data || [])[0] || {};
    if (!room.id_str) { console.log('⚠️ 签名正常，但这个房间号解析不到（填错/不是直播）'); process.exit(0); }
    console.log('   房间《' + (room.title || '').slice(0, 18) + '》status=' + room.status + (room.status === 2 ? '（在播）' : '（没在播，开播后自动连）'));
  }
  console.log('\n✅✅ 抖音通道健康：签名有效、服务端接受。点歌台里应显示 🟢');
})().catch(e => { console.log('❌ 异常：' + String(e.message || e).slice(0, 200)); process.exit(1); });
