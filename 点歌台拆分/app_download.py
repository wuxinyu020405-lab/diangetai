# -*- coding: utf-8 -*-
"""下载管线：QQ 音乐取址 / 缓存放回 / 音质降级 / 单首预算。

R-23 从 mainapp.py 搬出来的，逻辑一行没改，只是换了文件。"""

import asyncio
import os
import random
import time

import aiohttp
from qqmusic_api import Client
import musiclib
import settings
import state


class BudgetExceeded(Exception):
    """第7步：单首下载时间预算超限的内部信号（档位内流式写盘时抛出）。"""

    # R-23：原 mainapp._BudgetExceeded，搬过来后保留旧名字当别名，老代码不用改
    pass


_BudgetExceeded = BudgetExceeded


def _build_download_headers(credential):
    """按给定凭证构造流式下载用的请求头（CDN 只认 Cookie 里的 uin/musickey）。

    M2：凭证续期成功后 state.qq_credential 会被整个替换。若沿用续期前
    构造好的 headers，就会出现「取址用新凭证成功、下载仍带旧 musickey 被
    403」。所以凭证一变，这份头就必须用新凭证重新构造。
    """
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://y.qq.com/", "Origin": "https://y.qq.com",
        "Cookie": f"uin=o{credential.musicid}; qm_keyst={credential.musickey};",
    }


class DownloadMixin:
    """R-23：从 mainapp.MusicApp 拆出的方法块，靠多重继承合回同一个类。"""

    async def download_audio_qq(self, song_info, retries=3):
        self.last_download_reason = None
        song_mid = song_info.get("mid")
        display_name = song_info.get("display_name", "")
        # 第7步：单首总时间预算（串行管线的排队时长上界，23:49拍板 45s）
        dl_deadline = time.time() + settings.SONG_DOWNLOAD_BUDGET_SEC

        # 需求2·本地优先（置于凭证检查之前）：缓存命中即可播放，不需要下载，
        # 因此凭证过期/缺失时老缓存照样能用。
        any_cached = musiclib.find_any_cached_file(song_mid)
        if any_cached:
            self.last_download_reason = "cached"
            try: os.utime(any_cached, None)
            except Exception as e:
                print(f"[WARN] 缓存文件时间戳更新失败: {e}")
            return any_cached, display_name, song_mid

        if not state.qq_credential:
            self.last_download_reason = "no_credential"
            return None, None, None
        preferred_q = settings.normalize_quality_key(state.style_config.get("audio_quality", "flac"))
        chain = settings.QUALITY_FALLBACK_CHAINS.get(preferred_q, settings.QUALITY_FALLBACK_CHAINS["flac"])

        # 需求5：size_flac 预检（前置到所有网络动作之前）——
        # 搜索结果明确报无 FLAC(=0) 时，直接把 FLAC 档从链里剔掉，
        # 连 1.5s 预热和 CDN 请求都不用为它花。None=未知，保留该档（宁可多试不可漏放）。
        if song_info.get("flac_size") == 0:
            pruned = [t for t in chain if t[0] != "flac"]
            if pruned:
                self.log(f"[INFO] 搜索结果标记无 FLAC 音源(size_flac=0)，本首仅尝试: {[t[1] for t in pruned]}")
                chain = pruned

        # （本地优先缓存检索已置于函数顶部、凭证检查之前，避免在此重复）

        # 辅助函数：每次重试时重新获取CDN分发信息（避免使用过期的CDN节点）
        async def fetch_cdn():
            try:
                async with Client(credential=state.qq_credential) as client:
                    cdn_dispatch = await client.song.get_cdn_dispatch()
                    if hasattr(cdn_dispatch, 'sip') and cdn_dispatch.sip:
                        return random.choice(cdn_dispatch.sip)
            except Exception as e:
                print(f"[WARN] CDN分发信息获取失败: {e}")
            return ""

        # #4：原"下载前固定预热 1.5s"已移除。
        # 实测（2026-10-28，真实取址各 3 轮）：不预热 3/3 成功、预热后 3/3 成功，
        # result 码均为 0 —— 预热对成功率零贡献，纯属白白增加每次下载 1.5 秒延迟。
        if time.time() > dl_deadline:
            self.log(f"[{display_name}] 预算内未及开始取址（{settings.SONG_DOWNLOAD_BUDGET_SEC}s），本首放弃")
            self.last_download_reason = "budget"
            return None, display_name, song_mid

        # 首次获取CDN
        cdn = await fetch_cdn()
        if cdn:
            print(f"[INFO] 已获取CDN分发节点: {cdn}")

        # 下载请求头按当前凭证构造；续期后必须重建（见下面两处重建点）
        headers = _build_download_headers(state.qq_credential)

        for idx, (tier_key, tier_label, enum_names, default_ext, needs_enum) in enumerate(chain):
            # 第7步：单首预算——档位级检查，超时立即放弃整首（不再逐档烧时间）
            if time.time() > dl_deadline:
                self.log(f"[{display_name}] 超出单首预算({settings.SONG_DOWNLOAD_BUDGET_SEC}s)，放弃剩余档位")
                self.last_download_reason = "budget"
                return None, display_name, song_mid
            cached_tier_file = musiclib.find_cached_file_for_tier(song_mid, tier_key)
            if cached_tier_file:
                if idx > 0: self.log(f"无 {chain[0][1]} 音源，已使用本地缓存 [{tier_label}]")
                self.last_download_reason = "cached"
                try: os.utime(cached_tier_file, None)
                except Exception as e:
                    print(f"[WARN] 缓存文件时间戳更新失败: {e}")
                return cached_tier_file, display_name, song_mid

            # 每次音质降级时重新获取CDN
            cdn = await fetch_cdn()
            if cdn:
                self.log(f"已刷新CDN节点: {cdn}")

            # 使用 retries 参数控制重试次数（默认3次）
            cred_refreshed = False   # 本档位是否已尝试过凭证续期（最多1次）
            for attempt in range(retries):
                if time.time() > dl_deadline:
                    self.log(f"[{display_name}] 超出单首预算({settings.SONG_DOWNLOAD_BUDGET_SEC}s)，放弃剩余重试")
                    self.last_download_reason = "budget"
                    return None, display_name, song_mid
                try:
                    # 每次重试重新获取CDN节点（确保不复用过期节点）
                    if attempt > 0:
                        fresh_cdn = await fetch_cdn()
                        if fresh_cdn:
                            cdn = fresh_cdn
                            self.log(f"[INFO] 重试 [{tier_label}] (第{attempt+1}/{retries}次)，已刷新CDN节点: {fresh_cdn}")
                        else:
                            self.log(f"[WARN] 重试 [{tier_label}] (第{attempt+1}/{retries}次)，CDN刷新失败")

                    async with Client(credential=state.qq_credential) as client:
                        ft_enum = musiclib.resolve_song_file_type(client, enum_names) if needs_enum else None
                        if needs_enum and ft_enum is None:
                            self.log(f"[{tier_label}] 无法探测音质枚举类型，跳过此档位")
                            break

                        url_res = await musiclib.request_song_url_with_type(client, song_mid, ft_enum, state.qq_credential)
                        detail = musiclib.extract_url_detail(url_res, cdn=cdn)
                        fresh_url = detail["url"]
                        if attempt > 0 and fresh_url:
                            self.log(f"[INFO] 重试获取到新的下载URL (音质={tier_label})")

                        if not fresh_url:
                            code = detail.get("result")
                            why = detail.get("result_text") or "未知原因"
                            if code == 104013:
                                self.log(f"[{tier_label}] 播放设备受限(104013)，整首放弃，请重新扫码登录 QQ音乐")
                                self.last_download_reason = "device_limited"
                                return None, display_name, song_mid
                            if code == 104003:
                                self.log(f"[{tier_label}] 无该档位权限({why})，直接跳下一档")
                                break
                            if code == 104004 and not cred_refreshed:
                                cred_refreshed = True
                                new_cred = await musiclib.try_refresh_credential(state.qq_credential)
                                if new_cred:
                                    state.qq_credential = new_cred
                                    settings.save_credential(new_cred)
                                    # M2：凭证换新了，下载请求头必须同步重建——
                                    # 否则重试时取址用新 key、下载仍带旧 musickey → 403
                                    headers = _build_download_headers(state.qq_credential)
                                    self.log(f"[{tier_label}] VKey获取失败({why})，凭证已自动续期，重试本档")
                                    continue
                                self.log(f"[{tier_label}] VKey获取失败({why})，且凭证续期失败，跳档")
                                break
                            self.log(f"[{tier_label}] 未能获取下载URL：{why} (result={code})，跳过此档位")
                            break

                        selected_ext = musiclib.detect_ext_from_url(fresh_url, default_ext)
                        file_path = os.path.join(settings.CACHE_DIR, f"{song_mid}_{tier_key}{selected_ext}")
                        tmp_path = file_path + ".part"   # 第7步：半包防护，写完才改名

                        if attempt == 0:
                            self.log(f"[INFO] 首次下载 [{tier_label}]: {display_name} (URL有效期字段: {detail.get('expiration')})...")
                        else:
                            self.log(f"[INFO] 重试下载 [{tier_label}] (第{attempt+1}/{retries}次)...")

                        async with aiohttp.ClientSession(trust_env=False, headers=headers) as session:
                            async with session.get(fresh_url, timeout=aiohttp.ClientTimeout(total=30, connect=10)) as resp:
                                if resp.status in (200, 206):
                                    # 第7步：流式边读边写（不再整块进内存），边写边查单首预算
                                    total = 0
                                    try:
                                        with open(tmp_path, "wb") as f:
                                            async for chunk in resp.content.iter_chunked(64 * 1024):
                                                f.write(chunk)
                                                total += len(chunk)
                                                if time.time() > dl_deadline:
                                                    raise _BudgetExceeded()
                                    except _BudgetExceeded:
                                        try: os.remove(tmp_path)
                                        except OSError: pass
                                        raise
                                    except Exception:
                                        try: os.remove(tmp_path)
                                        except OSError: pass
                                        raise
                                    if total > musiclib.MIN_CACHE_BYTES:
                                        os.replace(tmp_path, file_path)   # 原子改名，其他读者永不见半包
                                        size_mb = total / (1024 * 1024)
                                        self.log(f"[INFO] ✅ 下载完成 [{tier_label}] ({size_mb:.1f} MB): {display_name} | 文件路径: {file_path}")
                                        musiclib.clean_cache_if_needed()
                                        self.last_download_reason = "downloaded"
                                        return file_path, display_name, song_mid
                                    else:
                                        try: os.remove(tmp_path)
                                        except OSError: pass
                                        self.log(f"[{tier_label}] 下载体过小({total}B)，判为无效并丢弃")
                                        break   # 该档放弃，走降级
                                elif resp.status == 403:
                                    self.log(f"[{tier_label}] 下载被拦截(403)，将刷新CDN节点和链接后重试...")
                                    retry_delay = 2 + random.uniform(0, 1.5)  # 基础2秒 + 随机抖动0~1.5秒
                                    self.log(f"[INFO] 403等待 {retry_delay:.1f}秒后重试 (CDN刷新+随机抖动避免限流)")
                                    await asyncio.sleep(retry_delay)
                                else:
                                    self.log(f"[{tier_label}] 下载失败: HTTP {resp.status}")
                                    break
                except _BudgetExceeded:
                    self.log(f"[{display_name}] 流式下载中途超出单首预算({settings.SONG_DOWNLOAD_BUDGET_SEC}s)，放弃")
                    self.last_download_reason = "budget"
                    return None, display_name, song_mid
                except Exception as e:
                    action, reason = musiclib.classify_api_exception(e)
                    if action == "quota":
                        self.log(f"[{tier_label}] ⛔ {reason} ({type(e).__name__})，停止本首后续尝试")
                        self.last_download_reason = "quota"
                        return None, display_name, song_mid
                    if action == "refresh_cred" and not cred_refreshed:
                        cred_refreshed = True
                        new_cred = await musiclib.try_refresh_credential(state.qq_credential)
                        if new_cred:
                            state.qq_credential = new_cred
                            settings.save_credential(new_cred)
                            # M2：同上——续期后重建下载请求头
                            headers = _build_download_headers(state.qq_credential)
                            self.log(f"[{tier_label}] {reason}，已自动续期凭证并重试本档")
                            continue
                        self.log(f"[{tier_label}] {reason}，且自动续期失败，请重新扫码登录 QQ音乐；跳过此档位")
                        break
                    if action == "skip":
                        self.log(f"[{tier_label}] 上游拒绝({reason}: {type(e).__name__})，不重试，跳过此档位")
                        break
                    self.log(f"[{tier_label}] 网络异常({reason}: {type(e).__name__})，退避后重试")
                    retry_delay = 2 + random.uniform(0, 1.5)  # 基础2秒 + 随机抖动
                    await asyncio.sleep(retry_delay)

            if idx < len(chain) - 1:
                self.log(f"当前音质 [{tier_label}] 全部失败，降级为 [{chain[idx+1][1]}] 尝试下载...")
                # 降级前等待更久，给服务器更多恢复时间
                fallback_delay = 3 + random.uniform(0, 2)
                self.log(f"[INFO] 降级前等待 {fallback_delay:.1f}秒，确保服务器状态恢复")
                await asyncio.sleep(fallback_delay)

        self.log(f"彻底无法下载《{display_name}》，所有音质均失败")
        self.last_download_reason = "all_failed"
        return None, display_name, song_mid
