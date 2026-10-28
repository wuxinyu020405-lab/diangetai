
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

function applyLyricOpacity(k, container) {
    // 滚动模式：JS 用 lyricOpK 乘各行相对透明度
    // 静态模式：CSS 变量 --lyric-op-base/--lyric-op-active（0.5*k / 1*k，兜底=旧值）
    lyricOpK = (typeof k === 'number' && k >= 0 && k <= 1) ? k : 1;
    container.style.setProperty('--lyric-op-base', String(0.5 * lyricOpK));
    container.style.setProperty('--lyric-op-active', String(1 * lyricOpK));
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
    const layoutKey = `${effectMode}_${activeIdx}_${prevCount}_${nextCount}_${style.size}_${style.align}_${style.is_bold}_${lyricOpK}_${window.innerHeight}_${window.innerWidth}`;   // 第6步：含透明度系数，滑杆即时生效

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
            const mixPfx = (cfg.mixed.show_prefix === false) ? '' : '🎵 正在播放: ';   // 第6步·修16.3-②
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
            applyLyricOpacity(cfg.lyric.opacity, lc);   // 第6步·透明度（与纯歌词共用 lyric.opacity）
            
            if (cfg.mixed.show_lyric) {
                lc.classList.remove('hidden-lyric');
                document.body.setAttribute('data-lyric-effect', cfg.mixed.effect_lyric);
                const mAlign = cfg.mixed.align || cfg.lyric.align || 'center';           // 第6步·修16.3-③
                const mPrev = (cfg.mixed.lines_prev !== undefined) ? cfg.mixed.lines_prev : cfg.lyric.lines_prev;
                const mNext = (cfg.mixed.lines_next !== undefined) ? cfg.mixed.lines_next : cfg.lyric.lines_next;
                const mixedStyle = { size: cfg.mixed.size_lyric, lines_prev: mPrev, lines_next: mNext, align: mAlign };
                if (cfg.mixed.effect_lyric === 'static') updateStaticLyric(data.lyric.lines, mAlign);
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
            applyLyricOpacity(cfg.lyric.opacity, lc);   // 第6步·透明度T-A
            document.body.setAttribute('data-lyric-effect', cfg.lyric.effect);
            
            if (cfg.lyric.effect === 'static') updateStaticLyric(data.lyric.lines, align);
            else updateAppleMusicScroll(data.lyric.all_lines, data.lyric.active_idx, cfg.lyric, cfg.lyric.effect, align);
        }
    } catch (e) {}
}
setInterval(updateData, 150); updateData();
