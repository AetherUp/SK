# -*- coding: utf-8 -*-
"""
快速测试：使用 Playwright 打开超星视频页面，验证能否正常播放和上报进度
"""
import asyncio
import os
import pickle
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from playwright.async_api import async_playwright


async def main():
    # 1) 先登录获取 cookies
    from api.base import Chaoxing, Account
    from api.answer import Tiku

    account = Account("13975076819", "Lzz20070613")
    chaoxing = Chaoxing(account=account, tiku=Tiku())

    print("登录中...")
    result = chaoxing.login()
    if not result["status"]:
        print(f"登录失败: {result['msg']}")
        return
    print("登录成功!")

    # 2) 获取课程和章节
    courses = chaoxing.get_course_list()
    course = None
    for c in courses:
        if c["courseId"] == "264391804":
            course = c
            break
    if not course:
        print("未找到课程 264391804")
        return

    print(f"课程: {course['title']}")

    points_data = chaoxing.get_course_point(course["courseId"], course["clazzId"], course["cpi"])
    points = points_data["points"]

    # 找第一个未完成的章节
    target_point = None
    for p in points:
        if not p["has_finished"]:
            target_point = p
            break
    if not target_point:
        target_point = points[0]  # fallback

    print(f"章节: {target_point['title']} (已完成: {target_point['has_finished']})")

    # 3) 获取任务点
    jobs, job_info = chaoxing.get_job_list(
        course["clazzId"], course["courseId"], course["cpi"], target_point["id"]
    )

    print(f"任务点数量: {len(jobs)}")
    video_jobs = [j for j in jobs if j["type"] == "video"]
    print(f"视频任务: {len(video_jobs)}")

    if not video_jobs:
        print("该章节无视频任务")
        return

    job = video_jobs[0]
    print(f"使用视频: {job['name']}")
    print(f"objectid: {job['objectid']}")

    # 4) 构造 URL 并用 Playwright 打开
    clazzId = course["clazzId"]
    courseId = course["courseId"]
    cpi = course["cpi"]
    knowledgeid = job_info.get("knowledgeid", "0")

    cards_url = (
        f"https://mooc1.chaoxing.com/mooc-ans/knowledge/cards?"
        f"clazzid={clazzId}&courseid={courseId}&knowledgeid={knowledgeid}&"
        f"num=0&ut=s&cpi={cpi}&v=20160407-3&mooc2=1"
    )

    print(f"\nURL: {cards_url}")

    # 加载 cookies（pickle 格式）
    cookies_path = os.path.join(os.path.dirname(__file__), "cookies.txt")
    pw_cookies = []
    if os.path.exists(cookies_path):
        with open(cookies_path, "rb") as f:
            cookie_jar = pickle.load(f)
        for cookie in cookie_jar:
            pw_cookies.append({
                "name": cookie.name,
                "value": cookie.value,
                "domain": cookie.domain,
                "path": cookie.path,
            })
        print(f"加载 {len(pw_cookies)} 个 cookies")
    else:
        print("警告: cookies.txt 不存在")
        from api.base import init_session
        _s = init_session()
        for c in _s.cookies:
            pw_cookies.append({
                "name": c.name, "value": c.value,
                "domain": c.domain, "path": c.path,
            })

    # 启动浏览器
    print("\n启动 Chromium...")
    # 查找 chrome.exe 路径
    chrome_paths = [
        r"C:\Users\ht\AppData\Local\ms-playwright\chromium-1223\chrome-win64\chrome.exe",
        r"C:\Users\ht\AppData\Local\ms-playwright\chromium_headless_shell-1223\chrome-headless-shell-win64\chrome-headless-shell.exe",
    ]
    chrome_exe = None
    for p_path in chrome_paths:
        if os.path.exists(p_path):
            chrome_exe = p_path
            break
    if not chrome_exe:
        print("❌ 未找到 Chromium 可执行文件!")
        return

    print(f"使用浏览器: {chrome_exe}")
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

        page = await context.new_page()

        # 监听关键请求
        log_requests = []
        async def on_request(req):
            if any(kw in req.url for kw in ["multimedia/log", "ananas/status"]):
                log_requests.append({"type": "request", "url": req.url, "time": time.time()})
        async def on_response(resp):
            if any(kw in resp.url for kw in ["multimedia/log", "ananas/status"]):
                try:
                    body = await resp.text()
                    body_preview = body[:300] if body else "(empty)"
                except Exception:
                    body_preview = "(无法读取)"
                log_requests.append({
                    "type": "response",
                    "url": resp.url,
                    "status": resp.status,
                    "body_preview": body_preview,
                    "time": time.time(),
                })
                print(f"\n[{resp.status}] {resp.url[:120]}")
                print(f"  Body: {body_preview}")

        page.on("request", on_request)
        page.on("response", on_response)

        # 导航到页面
        print(f"\n导航到知识卡片页面...")
        try:
            await page.goto(cards_url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"导航失败: {e}")

        await asyncio.sleep(2)

        # 检查页面状态
        page_title = await page.title()
        print(f"页面标题: {page_title}")
        page_url = page.url
        print(f"当前 URL: {page_url[:150]}")

        # 检查是否被重定向到登录页
        if "login" in page_url.lower() or "passport" in page_url.lower():
            print("❌ 被重定向到登录页面! Cookie 可能已过期")
            # 打印页面内容帮助调试
            content = await page.content()
            print(f"页面内容前500字符:\n{content[:500]}")
            await browser.close()
            return

        # 检查 frames - 找视频 iframe
        frames = page.frames
        print(f"\nFrame 数量: {len(frames)}")
        video_frame = None
        for i, f in enumerate(frames):
            print(f"  Frame {i}: {f.url[:120]}")
            if "ananas/modules/video" in f.url:
                video_frame = f
                print(f"  ^^^ 这是视频播放器 iframe!")

        if video_frame:
            print(f"\n===== 视频 iframe 详情 =====")
            try:
                # 检查 video 元素
                has_video = await video_frame.evaluate("() => !!document.querySelector('video')")
                print(f"video 元素存在: {has_video}")
                if has_video:
                    v_paused = await video_frame.evaluate("() => document.querySelector('video').paused")
                    print(f"video paused: {v_paused}")
                    v_duration = await video_frame.evaluate("() => document.querySelector('video').duration")
                    print(f"video duration: {v_duration}")
                    v_current = await video_frame.evaluate("() => document.querySelector('video').currentTime")
                    print(f"video currentTime: {v_current}")

                    # 强制播放！
                    print("强制开始播放...")
                    await video_frame.evaluate("""
                        () => {
                            const v = document.querySelector('video');
                            if (v) {
                                v.muted = false;
                                v.play().then(() => console.log('play OK')).catch(e => console.log('play error:', e));
                            }
                        }
                    """)
                    await asyncio.sleep(1)
                    v_paused_after = await video_frame.evaluate("() => document.querySelector('video').paused")
                    print(f"播放后 paused: {v_paused_after}")
                    v_current_after = await video_frame.evaluate("() => document.querySelector('video').currentTime")
                    print(f"播放后 currentTime: {v_current_after}")

                # 调试：检查页面上的 JS 变量和函数
                has_reader = await video_frame.evaluate("() => typeof reader !== 'undefined'")
                print(f"reader 对象存在: {has_reader}")
                has_getlog = await video_frame.evaluate("() => typeof getlog !== 'undefined'")
                print(f"getlog 函数存在: {has_getlog}")

                # 查看当前页面 URL 参数
                print(f"iframe URL: {video_frame.url[:200]}")
            except Exception as e:
                print(f"iframe 访问异常: {e}")

        # 等待观察 - 延长到 60 秒
        print(f"\n等待 60 秒观察请求...")
        for i in range(12):
            await asyncio.sleep(5)
            if video_frame:
                try:
                    ct = await video_frame.evaluate("() => { const v = document.querySelector('video'); return v ? v.currentTime : -1; }")
                    dur = await video_frame.evaluate("() => { const v = document.querySelector('video'); return v ? v.duration : -1; }")
                    paused = await video_frame.evaluate("() => { const v = document.querySelector('video'); return v ? v.paused : true; }")
                    if dur > 0:
                        print(f"  进度: {ct:.0f}/{dur:.0f}s ({ct/dur*100:.0f}%) | paused={paused} | 请求数={len(log_requests)}")
                except Exception:
                    pass

        print(f"\n===== 捕获到的请求 =====")
        for req in log_requests:
            print(f"[{req['type']}] {req.get('status', '-')} {req['url'][:150]}")

        if not log_requests:
            print("⚠️ 未捕获到任何 /multimedia/log/ 或 /ananas/status/ 请求!")
            print("可能原因: 视频 iframe 未加载, 或页面需要点击才能激活视频")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
