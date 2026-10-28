"""
OBS 浏览器源：HTML 模板与页面、数据接口路由
"""

from aiohttp import web
import state

# ================= OBS 网页渲染 =================
HTML_CONTENT = """
<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><title>OBS 源</title>
<style>
:root { 
    --font-playing: 'Microsoft YaHei', sans-serif; 
    --font-lyric: 'Microsoft YaHei', sans-serif; 
    --font-list: 'Microsoft YaHei', sans-serif;
    --lyric-font-size: 28px;
    --lyric-color: #FFE600;
    --lyric-font-weight: normal;
    --lyric-align: center;
    --lyric-origin: center center;
}
body {background-color: transparent;margin: 0;padding: 20px;font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'PingFang SC', 'Microsoft YaHei', sans-serif;overflow: hidden;-webkit-font-smoothing: antialiased;}
.hidden { display: none !important; }
.system-box {font-family: var(--font-playing); margin-bottom: 10px; text-shadow: 1px 1px 3px rgba(0,0,0,0.85); }
.lyric-box {
    margin-bottom: 16px;
    width: 100%;
    display: flex;
    flex-direction: column;
    align-items: var(--lyric-align);
    text-align: var(--lyric-align);
}
ul {list-style: none;padding: 0;margin: 0;}
li {font-family: var(--font-list); margin-bottom: 10px; text-shadow: 1px 1px 2px rgba(0,0,0,0.6); }
.empty {font-family: var(--font-list); color: #AAAAAA; text-shadow: 1px 1px 2px rgba(0,0,0,0.5); }

/* 纯歌词/综合挂件基础样式 */
.lyric-line {
    font-family: var(--font-lyric);
    font-size: var(--lyric-font-size);
    font-weight: var(--lyric-font-weight);
    color: var(--lyric-color);
    text-shadow: 1px 1px 3px rgba(0,0,0,0.9);
    padding: 4px 0;
    opacity: var(--lyric-op-base, 0.5);
    min-height: 1.2em;
    line-height: var(--lyric-line-height, 1.4);
}
.lyric-line.active {
    font-weight: bold;
    opacity: var(--lyric-op-active, 1);
}

/* 独立纯歌词模式 */
body.lyric-only-mode {
    display: flex;
    flex-direction: column;
    justify-content: center;
    height: 100vh;
    padding: 0;
    box-sizing: border-box;
    overflow: hidden;
}

/* 静态非滚动模式 */
body[data-lyric-effect="static"] .lyric-box {
    margin-bottom: 0;
    width: 100%;
    height: auto;
    display: flex;
    flex-direction: column;
    align-items: var(--lyric-align);
    text-align: var(--lyric-align);
    overflow: visible;
    -webkit-mask-image: none;
    mask-image: none;
}
body[data-lyric-effect="static"] .lyric-line {
    font-size: calc(var(--lyric-font-size) * 1.15);
    padding: 4px 0;
    opacity: var(--lyric-op-base, 0.5);
    filter: none;
    transform: none;
    transition: none;
    text-shadow: 1px 1px 3px rgba(0,0,0,0.9);
}
body[data-lyric-effect="static"] .lyric-line.active {
    font-weight: bold;
    opacity: var(--lyric-op-active, 1);
    text-shadow: 1px 1px 3px rgba(0,0,0,0.9);
}

/* 动效遮罩容器 */
body[data-lyric-effect="apple_blur"] .lyric-box,
body[data-lyric-effect="apple_hd"] .lyric-box {
    position: relative;
    width: 100%;
    height: 100vh;
    margin-bottom: 0;
    overflow: hidden;
    display: block;
}
body[data-lyric-effect="apple_blur"] .lyric-box {
    -webkit-mask-image: linear-gradient(to bottom, transparent 0%, rgba(0,0,0,0.85) 14%, rgba(0,0,0,1) 28%, rgba(0,0,0,1) 72%, rgba(0,0,0,0.85) 86%, transparent 100%);
    mask-image: linear-gradient(to bottom, transparent 0%, rgba(0,0,0,0.85) 14%, rgba(0,0,0,1) 28%, rgba(0,0,0,1) 72%, rgba(0,0,0,0.85) 86%, transparent 100%);
}
body[data-lyric-effect="apple_hd"] .lyric-box {
    -webkit-mask-image: linear-gradient(to bottom, transparent 0%, rgba(0,0,0,1) 8%, rgba(0,0,0,1) 92%, transparent 100%);
    mask-image: linear-gradient(to bottom, transparent 0%, rgba(0,0,0,1) 8%, rgba(0,0,0,1) 92%, transparent 100%);
}

/* 平滑滚动轨道 */
.lyric-track {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    display: flex;
    flex-direction: column;
    align-items: var(--lyric-align);
    text-align: var(--lyric-align);
    transition: transform 0.65s cubic-bezier(0.22, 1, 0.36, 1);
}
body[data-lyric-effect="apple_blur"] .lyric-track {
    will-change: transform;
}
.lyric-track.no-transition {
    transition: none !important;
}

/* 苹果景深滚动 (柔光) */
body[data-lyric-effect="apple_blur"] .lyric-line {
    font-size: calc(var(--lyric-font-size) * 1.15);
    line-height: var(--lyric-line-height, 1.42);
    padding: 10px 6%;
    box-sizing: border-box;
    max-width: 100%;
    word-break: break-word;
    transform-origin: var(--lyric-origin);
    will-change: transform, opacity, filter;
    transition:
        transform 0.65s cubic-bezier(0.22, 1, 0.36, 1),
        opacity 0.55s cubic-bezier(0.22, 1, 0.36, 1),
        filter 0.55s cubic-bezier(0.22, 1, 0.36, 1),
        text-shadow 0.55s ease;
    text-shadow: 0 2px 10px rgba(0,0,0,0.75);
}
body[data-lyric-effect="apple_blur"] .lyric-line.active {
    font-weight: 800;
    opacity: 1;
    filter: blur(0px);
    transform: scale(1.08) translateY(0px);
    text-shadow: 0 0 20px rgba(255, 255, 255, 0.32), 0 4px 14px rgba(0, 0, 0, 0.9);
}

/* 高清平滑滚动 (锐利) */
body[data-lyric-effect="apple_hd"] .lyric-line {
    font-size: calc(var(--lyric-font-size) * 1.12);
    line-height: var(--lyric-line-height, 1.42);
    padding: 9px 6%;
    box-sizing: border-box;
    max-width: 100%;
    word-break: break-word;
    filter: none !important;
    transition:
        transform 0.62s cubic-bezier(0.22, 1, 0.36, 1),
        opacity 0.5s cubic-bezier(0.22, 1, 0.36, 1);
    text-shadow: 1px 1px 3px rgba(0,0,0,0.95), -1px -1px 2px rgba(0,0,0,0.65), 0 2px 5px rgba(0,0,0,0.85);
}
body[data-lyric-effect="apple_hd"] .lyric-line.active {
    font-size: calc(var(--lyric-font-size) * 1.25);
    font-weight: 800;
    opacity: 1;
    filter: none !important;
    text-shadow: 1px 1px 3px rgba(0,0,0,0.98), -1px -1px 2px rgba(0,0,0,0.75), 0 3px 7px rgba(0,0,0,0.9);
}

/* 综合挂件特有样式调整 */
body.mixed-mode .lyric-box.hidden-lyric { height: 0 !important; margin: 0 !important; padding: 0 !important; overflow: hidden; display: none !important; }
body.mixed-mode .lyric-box { height: 250px; display: block; }
/* #2 综合源默认静态两行：高度自适应（否则 250px 盒子装两行会上下空出一大截）。
   滚动效果仍需要固定高度来做上下遮罩，故只对 static 生效。 */
body.mixed-mode[data-lyric-effect="static"] .lyric-box {
    height: auto; min-height: 0; display: flex; flex-direction: column;
    justify-content: center; margin-bottom: 10px;
}
body.playing-only-mode, body.queue-only-mode { display: flex; flex-direction: column; justify-content: center; height: 100vh; padding: 0; box-sizing: border-box; align-items: center; }
body.playing-only-mode .system-box { margin-bottom: 0; }
body.queue-only-mode ul { width: 100%; text-align: center; }
</style></head>
<body>
<div class="system-box" id="sys-playing">🎵 正在播放: 暂无</div>
<div class="lyric-box" id="lyric-container"></div>
<ul id="queue-list"><li class="empty">队列空闲中...</li></ul>
<script>
const path = window.location.pathname;
const isMixed = (path === '/' || path === '' || path === '/index.html');
const isLyric = path.includes('/lyric');
const isPlaying = path.includes('/playing');
const isQueue = path.includes('/queue');

if (isLyric) document.body.classList.add('lyric-only-mode');
if (isPlaying) document.body.classList.add('playing-only-mode');
if (isQueue) document.body.classList.add('queue-only-mode');
if (isMixed) document.body.classList.add('mixed-mode');

if (!isMixed) {
    if (!isPlaying) document.getElementById('sys-playing').style.display = 'none';
    if (!isLyric) document.getElementById('lyric-container').style.display = 'none';
    if (!isQueue) document.getElementById('queue-list').style.display = 'none';
}

let currentSongSignature = ''; 
let lastActiveIdx = -1; 
let lastLayoutKey = ''; 
let lastEffectMode = '';
let lyricOpK = 1;   // 第6步·透明度T-A系数（0~1），由 applyLyricOpacity 统一设置
let lyricLineH = 1.42;   // #6 行间距系数（line_spacing/100），由 updateData 设置

function applyLyricOpacity(k, spacing, container) {
    // 滚动模式：JS 用 lyricOpK 乘各行相对透明度
    // 静态模式：CSS 变量 --lyric-op-base/--lyric-op-active（0.5*k / 1*k，兜底=旧值）
    // #5：系数允许 0~2.0（>1 提亮非激活行；CSS 会把 opacity 自动钳到 1，不会出错）
    lyricOpK = (typeof k === 'number' && k >= 0 && k <= 2) ? Math.min(2, Math.max(0, k)) : 1;
    container.style.setProperty('--lyric-op-base', String(Math.min(1, 0.5 * lyricOpK)));
    container.style.setProperty('--lyric-op-active', String(Math.min(1, 1 * lyricOpK)));
    // #6 行间距：line_spacing 为百分比（默认142=现状），换算成 line-height 系数
    const lh = (typeof spacing === 'number' && spacing >= 100 && spacing <= 400) ? spacing / 100 : null;
    if (lh !== null) {
        lyricLineH = lh;
        container.style.setProperty('--lyric-line-height', String(lh));
    }
}

function updateStaticLyric(lines, align) {
    const container = document.getElementById('lyric-container');
    currentSongSignature = '';
    lastActiveIdx = -1;
    lastLayoutKey = '';
    container.style.textAlign = align;
    if (lines && lines.length > 0) { 
        let html = ''; 
        lines.forEach((l) => { 
            const cls = l.active ? 'lyric-line active' : 'lyric-line'; 
            const txt = l.text || ''; 
            html += `<div class="${cls}">${txt || '&nbsp;'}</div>`; 
        }); 
        container.innerHTML = html; 
    } else { 
        container.innerHTML = ''; 
    }
}

// #2 综合源专用：静态两行（当前行 + 下方 nextCount 行），无滚动动效。
// 后端 current_lyric_info 的窗口按 lyric.lines_prev/next 算，此处按 mixed 自己的
// 行数设置从 all_lines 重新截取，避免被纯歌词页的设置牵连。
function updateMixedTwoLine(allLines, activeIdx, prevCount, nextCount, align) {
    const container = document.getElementById('lyric-container');
    currentSongSignature = '';
    lastActiveIdx = -1;
    lastLayoutKey = '';
    container.style.textAlign = align;
    const track = document.getElementById('lyric-track');
    if (track) track.remove();          // 清掉滚动轨道，避免残留 transform
    if (!allLines || activeIdx < 0) { container.innerHTML = ''; return; }
    const start = Math.max(0, activeIdx - prevCount);
    const end = Math.min(allLines.length, activeIdx + nextCount + 1);
    let html = '';
    for (let i = start; i < end; i++) {
        const cls = (i === activeIdx) ? 'lyric-line active' : 'lyric-line';
        html += `<div class="${cls}">${allLines[i] || '&nbsp;'}</div>`;
    }
    container.innerHTML = html;
}

function updateAppleMusicScroll(allLines, activeIdx, style, effectMode, align) {
    const container = document.getElementById('lyric-container'); 
    let track = document.getElementById('lyric-track'); 
    const isEffectChanged = (effectMode !== lastEffectMode);

    if (!track) { 
        container.innerHTML = '<div class="lyric-track no-transition" id="lyric-track"></div>'; 
        track = document.getElementById('lyric-track'); 
    }
    track.style.textAlign = align;

    if (!allLines || allLines.length === 0 || activeIdx < 0) { 
        track.innerHTML = ''; 
        currentSongSignature = ''; 
        lastActiveIdx = -1; 
        lastEffectMode = effectMode; 
        return; 
    }

    const signature = allLines.length + '::' + allLines[0] + '::' + allLines[allLines.length - 1] + '::' + allLines.join('|');
    const isNewSong = (signature !== currentSongSignature);

    if (isNewSong) { 
        currentSongSignature = signature; 
        lastActiveIdx = -1; 
        track.classList.add('no-transition'); 
        track.innerHTML = ''; 
        allLines.forEach((txt) => { 
            const div = document.createElement('div'); 
            div.className = 'lyric-line'; 
            div.textContent = txt || '\u00A0'; 
            track.appendChild(div); 
        }); 
    } else if (isEffectChanged) { 
        track.classList.add('no-transition'); 
    }

    const prevCount = (style.lines_prev !== undefined) ? style.lines_prev : 2; 
    const nextCount = (style.lines_next !== undefined) ? style.lines_next : 2;
    const layoutKey = `${effectMode}_${activeIdx}_${prevCount}_${nextCount}_${style.size}_${style.align}_${style.is_bold}_${lyricOpK}_${lyricLineH}_${window.innerHeight}_${window.innerWidth}`;   // 第6步：含透明度/行距系数，滑杆即时生效

    if (!isNewSong && !isEffectChanged && layoutKey === lastLayoutKey) { 
        return; 
    }

    const isStepForward = (!isNewSong && !isEffectChanged && lastActiveIdx >= 0 && activeIdx === lastActiveIdx + 1);
    lastActiveIdx = activeIdx; 
    lastLayoutKey = layoutKey; 
    lastEffectMode = effectMode;

    const children = track.children; 
    const total = children.length; 
    if (total === 0) return;

    const clampedIdx = Math.max(0, Math.min(total - 1, activeIdx)); 
    const minVis = clampedIdx - prevCount; 
    const maxVis = clampedIdx + nextCount;
    const isHD = (effectMode === 'apple_hd');
    const opK = lyricOpK;   // 第6步·透明度T-A：本帧统一用同一系数

    for (let i = 0; i < total; i++) {
        const el = children[i]; 
        const dist = i - clampedIdx; 
        const absDist = Math.abs(dist);

        if (isStepForward && i >= minVis - 1 && i <= maxVis + 1) {
            const order = Math.max(0, i - minVis);
            el.style.transitionDelay = `${Math.min(order * 28, 180)}ms`;
        } else {
            el.style.transitionDelay = '0ms';
        }

        if (i === clampedIdx) { 
            el.className = 'lyric-line active'; 
            el.style.opacity = String(1 * opK);   // 第6步·透明度T-A：系数等比缩放
            el.style.pointerEvents = 'auto';
            if (isHD) {
                el.style.filter = 'none';
                el.style.transform = 'translateY(0px)';
            } else {
                el.style.filter = 'blur(0px)';
                el.style.transform = 'scale(1.08) translateY(0px)';
            }
        } else if (i >= minVis && i <= maxVis) { 
            el.className = 'lyric-line'; 
            el.style.pointerEvents = 'auto';
            if (isHD) {
                let opacity = 0.72;
                if (absDist === 2) opacity = 0.52;
                else if (absDist === 3) opacity = 0.36;
                else if (absDist >= 4) opacity = 0.24;
                el.style.opacity = String(opacity * opK);
                el.style.filter = 'none';
                el.style.transform = 'translateY(0px)';
            } else {
                let opacity = 0.58;
                if (absDist === 2) opacity = 0.36;
                else if (absDist === 3) opacity = 0.22;
                else if (absDist >= 4) opacity = 0.14;
                const blurPx = Math.min(absDist * 0.85, 3.6).toFixed(2);
                el.style.opacity = String(opacity * opK);
                el.style.filter = `blur(${blurPx}px)`;
                el.style.transform = 'scale(0.96) translateY(0px)';
            }
        } else { 
            el.className = 'lyric-line'; 
            el.style.opacity = '0'; 
            el.style.pointerEvents = 'none';
            const shiftY = dist < 0 ? -10 : 10;
            if (isHD) {
                el.style.filter = 'none';
                el.style.transform = `translateY(${shiftY}px)`;
            } else {
                el.style.filter = 'blur(5px)';
                el.style.transform = `scale(0.92) translateY(${shiftY}px)`;
            }
        }
    }

    const activeEl = children[clampedIdx];
    if (activeEl) { 
        const viewportH = container.clientHeight || window.innerHeight; 
        const activeCenter = activeEl.offsetTop + activeEl.offsetHeight / 2; 
        const avgLineH = activeEl.offsetHeight || 52;
        const focalY = (viewportH / 2) - ((nextCount - prevCount) * avgLineH * 0.45);
        const targetY = focalY - activeCenter; 
        if (isHD) {
            track.style.transform = `translateY(${Math.round(targetY)}px)`;
        } else {
            track.style.transform = `translate3d(0, ${targetY.toFixed(1)}px, 0)`;
        }
    }

    if (isNewSong || isEffectChanged) { 
        requestAnimationFrame(() => { 
            requestAnimationFrame(() => { 
                if (track) track.classList.remove('no-transition'); 
            }); 
        }); 
    }
}

window.addEventListener('resize', () => {
    lastLayoutKey = '';
});

async function updateData() {
    try {
        const response = await fetch('/api/data'); 
        const data = await response.json(); 
        const cfg = data.style; 
        const root = document.documentElement;

        if (isMixed) {
            root.style.setProperty('--font-playing', cfg.mixed.font_playing);
            root.style.setProperty('--font-lyric', cfg.mixed.font_lyric);
            root.style.setProperty('--font-list', cfg.mixed.font_queue);
            
            const sys = document.getElementById('sys-playing');
            sys.style.fontSize = cfg.mixed.size_playing + 'px'; 
            sys.style.color = cfg.mixed.color_playing;
            sys.style.fontWeight = cfg.mixed.bold_playing ? 'bold' : 'normal';
            sys.classList.toggle('hidden', !cfg.mixed.show_playing);
            // #3：把"🎵"图标与"正在播放:"文字拆成两个独立开关
            //   show_icon=false    → 去掉 🎵
            //   show_prefix=false  → 去掉"正在播放:"（图标仍可保留）
            const mixIcon = (cfg.mixed.show_icon === false) ? '' : '🎵 ';
            const mixWord = (cfg.mixed.show_prefix === false) ? '' : '正在播放: ';
            const mixPfx = mixIcon + mixWord;
            const sysText = (data.system_playing && data.system_playing !== "暂无播放") ? (mixPfx + data.system_playing) : (mixPfx + '暂无');
            sys.innerText = sysText;
            
            const ul = document.getElementById('queue-list');
            ul.style.fontSize = cfg.mixed.size_queue + 'px'; 
            ul.style.color = cfg.mixed.color_queue;
            ul.style.fontWeight = cfg.mixed.bold_queue ? 'bold' : 'normal';
            ul.classList.toggle('hidden', !cfg.mixed.show_queue);
            // 第6步·高价值3/5/6：条数上限/序号/请求者 可配（默认=旧行为：全部显示、带序号、sep='-'）
            const mItems = (cfg.mixed.max_items && cfg.mixed.max_items > 0) ? data.list.slice(0, cfg.mixed.max_items) : data.list;
            if (mItems.length === 0) {
                ul.innerHTML = '<li class="empty">队列空闲中...</li>';
            } else {
                let html = '';
                const mIdx = cfg.mixed.show_index !== false;
                const mReq = cfg.mixed.show_requester !== false;
                const mSep = (cfg.mixed.requester_sep !== undefined) ? cfg.mixed.requester_sep : '-';
                const mMax = cfg.mixed.max_chars || 0;
                mItems.forEach((item, index) => {
                    let reqStr = (mReq && item.requester) ? (mSep + item.requester) : '';
                    let s = (mIdx ? `${index + 1}. ` : '') + item.display_name + reqStr;
                    if (mMax > 0 && s.length > mMax) s = s.substring(0, mMax) + '...';   // 第6步·修16.3-①
                    html += `<li>${s}</li>`;
                });
                ul.innerHTML = html;
            }

            const lc = document.getElementById('lyric-container');
            lc.style.setProperty('--lyric-font-size', cfg.mixed.size_lyric + 'px');
            lc.style.setProperty('--lyric-color', cfg.mixed.color_lyric);
            lc.style.setProperty('--lyric-font-weight', cfg.mixed.bold_lyric ? 'bold' : 'normal');
            applyLyricOpacity(cfg.lyric.opacity, cfg.lyric.line_spacing, lc);   // 第6步·透明度+行距（mixed 共用）
            // 对齐：mixed 自己有 align，需同时设置 flex 交叉轴变量，
            // 否则 .lyric-box 的 align-items 会压过 text-align（表现为"改了没反应"）
            const mAlignNow = cfg.mixed.align || cfg.lyric.align || 'center';
            const mFlex = {'left': 'flex-start', 'right': 'flex-end', 'center': 'center'}[mAlignNow] || 'center';
            lc.style.setProperty('--lyric-align', mFlex);
            lc.style.alignItems = mFlex;
            lc.style.textAlign = mAlignNow;
            root.style.setProperty('--lyric-origin', (mAlignNow === 'left') ? 'left center'
                                   : (mAlignNow === 'right') ? 'right center' : 'center center');
            
            if (cfg.mixed.show_lyric) {
                lc.classList.remove('hidden-lyric');
                document.body.setAttribute('data-lyric-effect', cfg.mixed.effect_lyric);
                const mAlign = cfg.mixed.align || cfg.lyric.align || 'center';           // 第6步·修16.3-③
                const mPrev = (cfg.mixed.lines_prev !== undefined) ? cfg.mixed.lines_prev : cfg.lyric.lines_prev;
                const mNext = (cfg.mixed.lines_next !== undefined) ? cfg.mixed.lines_next : cfg.lyric.lines_next;
                const mixedStyle = { size: cfg.mixed.size_lyric, lines_prev: mPrev, lines_next: mNext, align: mAlign };
                if (cfg.mixed.effect_lyric === 'static') updateMixedTwoLine(data.lyric.all_lines, data.lyric.active_idx, mPrev, mNext, mAlign);
                else updateAppleMusicScroll(data.lyric.all_lines, data.lyric.active_idx, mixedStyle, cfg.mixed.effect_lyric, mAlign);
            } else { 
                lc.classList.add('hidden-lyric');
                lc.innerHTML = '';
            }
        } 
        else if (isPlaying) {
            const sys = document.getElementById('sys-playing');
            sys.style.fontFamily = cfg.playing.font;
            sys.style.fontSize = cfg.playing.size + 'px';
            sys.style.color = cfg.playing.color;
            sys.style.fontWeight = cfg.playing.is_bold ? 'bold' : 'normal';
            const txt = data.system_playing;
            sys.innerText = cfg.playing.show_prefix ? ('🎵 正在播放: ' + txt) : txt;
        } 
        else if (isQueue) {
            const ul = document.getElementById('queue-list');
            ul.style.fontFamily = cfg.queue.font;
            ul.style.fontSize = cfg.queue.size + 'px';
            ul.style.color = cfg.queue.color;
            ul.style.fontWeight = cfg.queue.is_bold ? 'bold' : 'normal';
            const max = cfg.queue.max_chars || 999;
            // 第6步·高价值3/5/6（queue-only 页同样可配）
            const qItems = (cfg.queue.max_items && cfg.queue.max_items > 0) ? data.list.slice(0, cfg.queue.max_items) : data.list;
            if (qItems.length === 0) ul.innerHTML = '<li class="empty">队列空闲中...</li>';
            else {
                const qIdx = cfg.queue.show_index !== false;
                const qReq = cfg.queue.show_requester !== false;
                const qSep = (cfg.queue.requester_sep !== undefined) ? cfg.queue.requester_sep : '-';
                let html = ''; qItems.forEach((item, i) => {
                    let s = (qIdx ? `${i+1}. ` : '') + item.display_name + (qReq && item.requester ? qSep+item.requester : '');
                    if (s.length > max) s = s.substring(0, max) + '...';
                    html += `<li>${s}</li>`;
                }); ul.innerHTML = html;
            }
        } 
        else if (isLyric) {
            root.style.setProperty('--font-lyric', cfg.lyric.font);
            let align = 'center';
            let flexAlign = 'center';
            let origin = 'center center';
            if (cfg.lyric.align === 'left') {
                align = 'left'; flexAlign = 'flex-start'; origin = 'left center';
            } else if (cfg.lyric.align === 'right') {
                align = 'right'; flexAlign = 'flex-end'; origin = 'right center';
            }
            root.style.setProperty('--lyric-align', flexAlign);
            root.style.setProperty('--lyric-origin', origin);

            const lc = document.getElementById('lyric-container');
            lc.style.setProperty('--lyric-font-size', cfg.lyric.size + 'px');
            lc.style.setProperty('--lyric-color', cfg.lyric.color);
            lc.style.setProperty('--lyric-font-weight', cfg.lyric.is_bold ? 'bold' : 'normal');
            applyLyricOpacity(cfg.lyric.opacity, cfg.lyric.line_spacing, lc);   // 第6步·透明度T-A + #6行距
            document.body.setAttribute('data-lyric-effect', cfg.lyric.effect);
            
            if (cfg.lyric.effect === 'static') updateStaticLyric(data.lyric.lines, align);
            else updateAppleMusicScroll(data.lyric.all_lines, data.lyric.active_idx, cfg.lyric, cfg.lyric.effect, align);
        }
    } catch (e) {}
}
setInterval(updateData, 150); updateData();
</script></body></html>
"""

async def handle_index(request): return web.Response(text=HTML_CONTENT, content_type='text/html')

async def handle_api(request):
    global system_media_info, current_lyric_info
    sys_text = state.system_media_info.get("title", "暂无播放"); artist = state.system_media_info.get("artist", "")
    if artist and sys_text != "暂无播放": sys_text += f" - {artist}"
    data = {"current": state.current_song, "list": state.playlist, "style": state.style_config, "system_playing": sys_text, "lyric": state.current_lyric_info}
    return web.json_response(data)
