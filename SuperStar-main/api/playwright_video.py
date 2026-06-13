# -*- coding: utf-8 -*-
"""
Playwright 视频播放模块
使用真实 Chromium 浏览器打开超星视频页面，让页面 JS 自动处理 MD5 加密
和进度上报，彻底解决直接 HTTP 请求导致的 403 问题。

原理：超星视频页面加载时会自动调用 /ananas/status 获取视频信息，
然后周期性调用 /multimedia/log/a/ 上报进度。页面 JS 使用真实的
videoFaceCaptureEnc / attDurationEnc 签名，不会被 WAF 拦截。
"""
import asyncio
import os
import pickle
import time
from api.logger import logger


async def _study_video_playwright_async(course, job, job_info, speed=1.0) -> bool:
    """
    在 Playwright 浏览器中完成单个视频任务。

    流程：
    1. 加载 cookies（从 pickle 文件）
    2. 启动 headless Chromium
    3. 遍历 num=0~6 找到包含目标视频的知识卡片页
    4. 在 video iframe 中强制播放视频
    5. 等待视频进度达到 100%
    6. 关闭浏览器并返回结果

    Returns:
        True=视频完成, False=失败
    """
    objectid = job.get("objectid", "")
    clazzId = course["clazzId"]
    courseId = course["courseId"]
    cpi = course["cpi"]
    knowledgeid = job_info.get("knowledgeid", "0")
    video_name = job.get("name", objectid)
    cookies_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cookies.txt"
    )

    # 查找 Chrome 可执行文件
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    chrome_paths = [
        os.path.join(local_appdata, "ms-playwright", "chromium-1223",
                     "chrome-win64", "chrome.exe"),
        os.path.join(local_appdata, "ms-playwright", "chromium_headless_shell-1223",
                     "chrome-headless-shell-win64", "chrome-headless-shell.exe"),
    ]
    chrome_exe = None
    for _p in chrome_paths:
        if os.path.exists(_p):
            chrome_exe = _p
            break
    if not chrome_exe:
        logger.error("[Playwright] 未找到 Chromium 可执行文件")
        return False

    # 加载 cookies
    pw_cookies = []
    if os.path.exists(cookies_path):
        try:
            with open(cookies_path, "rb") as f:
                cookie_jar = pickle.load(f)
            for cookie in cookie_jar:
                pw_cookies.append({
                    "name": cookie.name, "value": cookie.value,
                    "domain": cookie.domain, "path": cookie.path,
                })
        except Exception as e:
            logger.warning(f"[Playwright] Cookie 加载失败: {e}")
            return False
    else:
        logger.error("[Playwright] cookies.txt 不存在")
        return False

    logger.info(f"[Playwright] 视频: {video_name} (objectid={objectid[:16]}...)")

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            executable_path=chrome_exe,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--autoplay-policy=no-user-gesture-required",
                "--mute-audio",
            ],
        )

        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/149.0.0.0 Safari/537.36 Edg/149.0.0.0"
            ),
        )
        await context.add_cookies(pw_cookies)

        video_finished = False
        found_video = False
        last_progress_time = time.time()

        for num in range(7):  # 尝试 num=0 到 6 找到视频
            if found_video:
                break

            cards_url = (
                f"https://mooc1.chaoxing.com/mooc-ans/knowledge/cards?"
                f"clazzid={clazzId}&courseid={courseId}&knowledgeid={knowledgeid}&"
                f"num={num}&ut=s&cpi={cpi}&v=20160407-3&mooc2=1"
            )

            page = await context.new_page()
            try:
                await page.goto(cards_url, wait_until="domcontentloaded", timeout=30000)
            except Exception:
                await page.close()
                continue

            await asyncio.sleep(2)

            # 找视频 iframe
            video_frame = None
            for frame in page.frames:
                if "ananas/modules/video" in frame.url:
                    video_frame = frame
                    break

            if not video_frame:
                logger.debug(f"[Playwright] num={num} 无视频 iframe，尝试下一个")
                await page.close()
                continue

            # 验证这个 iframe 里的视频是否是我们需要处理的
            try:
                frame_objid = await video_frame.evaluate(
                    "() => { try { return videoObj.attrid; } catch(e) { return ''; } }"
                )
            except Exception:
                frame_objid = ""

            if frame_objid and frame_objid != objectid:
                logger.debug(f"[Playwright] num={num} objectid 不匹配 ({frame_objid} != {objectid})")
                await page.close()
                continue

            # 找到了！
            found_video = True
            logger.info(f"[Playwright] 找到视频 (num={num}), 开始播放...")

            # 获取视频时长
            try:
                duration = await video_frame.evaluate(
                    "() => { const v = document.querySelector('video'); return v ? v.duration : 0; }"
                )
                current = await video_frame.evaluate(
                    "() => { const v = document.querySelector('video'); return v ? v.currentTime : 0; }"
                )
                if duration and duration > 0:
                    logger.info(f"[Playwright] 视频总长 {duration:.0f}s, 当前进度 {current:.0f}s ({current/duration*100:.0f}%)")
            except Exception:
                duration = 0

            # 强制播放
            try:
                await video_frame.evaluate("""
                    () => {
                        const v = document.querySelector('video');
                        if (v && v.paused) { v.play().catch(() => {}); }
                    }
                """)
            except Exception:
                pass

            # 等待视频完成 (最长 60 分钟)
            max_wait = 3600
            check_interval = 10

            for _ in range(max_wait // check_interval):
                await asyncio.sleep(check_interval)

                try:
                    current = await video_frame.evaluate(
                        "() => { const v = document.querySelector('video'); return v ? v.currentTime : 0; }"
                    )
                    dur = await video_frame.evaluate(
                        "() => { const v = document.querySelector('video'); return v ? v.duration : 0; }"
                    )
                    paused = await video_frame.evaluate(
                        "() => { const v = document.querySelector('video'); return v ? v.paused : true; }"
                    )
                except Exception:
                    # 页面可能已关闭或导航
                    break

                if dur > 0 and current > 0:
                    pct = current / dur * 100
                    elapsed = time.time() - last_progress_time
                    logger.info(f"[Playwright] 视频进度: {current:.0f}/{dur:.0f}s ({pct:.0f}%) | paused={paused}")

                    # 如果视频暂停且接近结束 (>=99%)，视为完成
                    if paused and pct >= 99:
                        logger.info(f"[Playwright] 视频已完成 ({pct:.0f}%)")
                        video_finished = True
                        break

                    # 如果暂停但不是接近结束，尝试恢复播放
                    if paused and pct < 99:
                        logger.debug("[Playwright] 视频暂停中，尝试恢复...")
                        try:
                            await video_frame.evaluate("""
                                () => { const v = document.querySelector('video'); if (v) v.play().catch(() => {}); }
                            """)
                        except Exception:
                            pass

                # 超过 180 秒无进展，可能卡住了
                if time.time() - last_progress_time > 180:
                    logger.warning("[Playwright] 视频可能卡住，尝试恢复...")
                    try:
                        await video_frame.evaluate("""
                            () => { const v = document.querySelector('video'); if (v) v.play().catch(() => {}); }
                        """)
                    except Exception:
                        pass
                    last_progress_time = time.time()

            await page.close()

        await browser.close()

    if video_finished:
        logger.info(f"[Playwright] 视频任务完成: {video_name}")
    else:
        if not found_video:
            logger.warning(f"[Playwright] 未找到视频 iframe (已尝试 num=0~6)")
        else:
            logger.warning(f"[Playwright] 视频未正常完成: {video_name}")

    return video_finished


def study_video_playwright(course, job, job_info, speed=1.0) -> bool:
    """
    同步包装器，供 main.py 调用。

    Returns:
        True=视频完成, False=失败（应回退到 HTTP 方式重试）
    """
    try:
        return asyncio.run(
            _study_video_playwright_async(course, job, job_info, speed)
        )
    except Exception as e:
        logger.error(f"[Playwright] 异常: {e}")
        return False
