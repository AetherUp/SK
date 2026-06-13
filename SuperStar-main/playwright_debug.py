# -*- coding: utf-8 -*-
"""
Playwright 诊断脚本：捕获超星视频播放时的真实浏览器请求
对比 Python 脚本生成的请求，找出 403 根因
"""
import asyncio
import json
import re
import sys
import os
from hashlib import md5

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from playwright.async_api import async_playwright
from api.base import Chaoxing, Account
from api.answer import Tiku
from api.logger import logger


def load_cookies_from_file():
    """从文件加载 cookies"""
    cookies_path = os.path.join(os.path.dirname(__file__), "cookies.txt")
    if not os.path.exists(cookies_path):
        return None
    try:
        with open(cookies_path, "r") as f:
            return json.load(f)
    except Exception:
        return None


def cookies_to_playwright(requests_cookies):
    """将 requests 的 CookieJar 转为 Playwright 格式"""
    pw_cookies = []
    for cookie in requests_cookies:
        pw_cookie = {
            "name": cookie.name,
            "value": cookie.value,
            "domain": cookie.domain,
            "path": cookie.path,
        }
        if cookie.expires:
            pw_cookie["expires"] = cookie.expires
        pw_cookies.append(pw_cookie)
    return pw_cookies


async def capture_video_requests(course, job, job_info, session_cookies):
    """
    使用 Playwright 打开视频页面，拦截所有 /multimedia/log/a/ 请求
    打印真实浏览器的请求参数，用于对比调试
    """
    # 构造视频页面 URL
    # 超星视频播放器页面需要这些参数
    otherinfo = job.get("otherinfo", "")
    objectid = job.get("objectid", "")
    clazzId = course["clazzId"]
    courseId = course["courseId"]
    cpi = course["cpi"]
    knowledgeid = job_info.get("knowledgeid", "")

    # 视频播放器页面 URL - 带参数
    video_page_url = (
        f"https://mooc1.chaoxing.com/ananas/modules/video/index.html?"
        f"v=2026-0604-1025&"
        f"objectid={objectid}&"
        f"courseid={courseId}&"
        f"clazzid={clazzId}&"
        f"cpi={cpi}&"
        f"knowledgeid={knowledgeid}&"
        f"{otherinfo}"
    )

    # 方法2：通过 knowledge/cards 页面进入（可能更接近真实流程）
    cards_url = (
        f"https://mooc1.chaoxing.com/mooc-ans/knowledge/cards?"
        f"clazzid={clazzId}&"
        f"courseid={courseId}&"
        f"knowledgeid={knowledgeid}&"
        f"num=0&"
        f"ut=s&"
        f"cpi={cpi}&"
        f"v=20160407-3&"
        f"mooc2=1"
    )

    captured_requests = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36 Edg/149.0.0.0"
        )

        # 设置 cookies
        if session_cookies:
            pw_cookies = cookies_to_playwright(session_cookies)
            await context.add_cookies(pw_cookies)

        page = await context.new_page()

        # 拦截所有 /multimedia/log/ 请求
        async def on_request(request):
            if "multimedia/log" in request.url:
                captured_requests.append({
                    "url": request.url,
                    "method": request.method,
                    "headers": dict(request.headers),
                    "timestamp": asyncio.get_event_loop().time(),
                })
                print(f"\n[拦截请求] /multimedia/log/a/")
                print(f"URL: {request.url}")

        page.on("request", on_request)

        # 先尝试 knowledge/cards 页面（包含视频 iframe）
        print(f"\n===== 方法1: 直接访问视频播放器页面 =====")
        print(f"URL: {video_page_url}")
        try:
            await page.goto(video_page_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)
            # 检查页面内容
            page_title = await page.title()
            print(f"页面标题: {page_title}")

            # 等待页面 JS 运行
            await asyncio.sleep(3)

            # 检查是否有 iframe
            iframes = page.frames
            print(f"页面 frame 数量: {len(iframes)}")

            # 等待视频加载和播放（最多等待 30 秒观察请求）
            print("等待视频播放器发送请求...")
            await asyncio.sleep(10)
        except Exception as e:
            print(f"方法1 失败: {e}")

        if not captured_requests:
            print(f"\n===== 方法2: 通过 knowledge/cards 页面进入 =====")
            print(f"URL: {cards_url}")
            try:
                await page.goto(cards_url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3)

                # 检查页面内容
                page_content = await page.content()
                # 查找视频 iframe
                if "iframe" in page_content:
                    print("页面包含 iframe")
                    # 尝试在 iframe 中操作
                    frames = page.frames
                    print(f"页面 frame 数量: {len(frames)}")
                    for i, frame in enumerate(frames):
                        frame_url = frame.url
                        print(f"Frame {i}: {frame_url[:100]}")

                print("等待视频播放器发送请求...")
                await asyncio.sleep(15)
            except Exception as e:
                print(f"方法2 失败: {e}")

        await browser.close()

    return captured_requests


def analyze_script_request(course, job, job_info):
    """打印 Python 脚本生成的请求参数，用于对比"""
    clazzId = course["clazzId"]
    courseId = course["courseId"]
    userid = "mock_uid"  # 实际运行时会从 self.get_uid() 获取
    jobid = job["jobid"]
    objectId = job["objectid"]
    duration = 600  # 假设 10 分钟视频
    playingTime = 0
    otherinfo = job.get("otherinfo", "")

    # 复制脚本的加密逻辑
    def _md5enc(clazzId, userid, jobid, objectId, value, duration, suffix):
        return md5(
            f"[{clazzId}][{userid}][{jobid}][{objectId}][{value * 1000}][d_yHJ!$pdA~5][{duration * 1000}][{suffix}]".encode()
        ).hexdigest()

    _enc = _md5enc(clazzId, userid, jobid, objectId, playingTime, duration, f"0_{duration}")
    _vfce = _md5enc(clazzId, userid, jobid, objectId, 0, duration, "0_0")
    _ade = _md5enc(clazzId, userid, jobid, objectId, duration, duration, f"0_{duration}")

    _raw_other = otherinfo
    if "courseId=" in _raw_other:
        _raw_other = re.sub(r"&?courseId=\d+", "", _raw_other)

    print("\n===== Python 脚本生成的请求参数 =====")
    print(f"enc = {_enc}")
    print(f"videoFaceCaptureEnc = {_vfce}")
    print(f"attDurationEnc = {_ade}")
    print(f"otherInfo = {_raw_other}")
    print(f"courseId = {courseId}")
    print(f"clazzId = {clazzId}")
    print(f"objectId = {objectId}")
    print(f"jobid = {jobid}")
    print(f"userid = {userid}")
    print(f"playingTime = {playingTime}")
    print(f"duration = {duration}")
    print(f"isdrag = 2/3/4/0")
    print(f"rt = 0.9/1")
    print(f"clipTime = 0_{duration}")


async def main():
    """主函数"""
    # 初始化超星实例（仅用于登录获取 cookies 和课程信息）
    username = input("手机号: ").strip()
    password = input("密码: ").strip()

    account = Account(username, password)
    tiku = Tiku()
    chaoxing = Chaoxing(account=account, tiku=tiku)

    # 登录
    print("正在登录...")
    login_result = chaoxing.login()
    if not login_result["status"]:
        print(f"登录失败: {login_result['msg']}")
        return

    print("登录成功!")

    # 获取课程列表
    all_courses = chaoxing.get_course_list()
    print(f"\n课程列表 ({len(all_courses)} 门):")
    for i, c in enumerate(all_courses):
        print(f"  [{i}] {c['courseId']} - {c['title']}")

    # 选择课程
    course_id = input("\n输入要调试的课程ID: ").strip()
    course = None
    for c in all_courses:
        if c["courseId"] == course_id:
            course = c
            break

    if not course:
        print("未找到该课程")
        return

    # 获取章节
    point_list = chaoxing.get_course_point(course["courseId"], course["clazzId"], course["cpi"])
    points = point_list["points"]

    print(f"\n章节列表 ({len(points)} 个):")
    for i, pt in enumerate(points):
        status = "已完成" if pt["has_finished"] else "未完成"
        print(f"  [{i}] {pt['title']} - {status}")

    # 选择章节
    pt_idx = int(input("\n选择章节序号: ").strip())
    point = points[pt_idx]

    # 获取任务点
    jobs, job_info = chaoxing.get_job_list(
        course["clazzId"], course["courseId"], course["cpi"], point["id"]
    )

    print(f"\n任务点列表 ({len(jobs)} 个):")
    for i, j in enumerate(jobs):
        print(f"  [{i}] {j['type']} - {j.get('name', j.get('title', 'N/A'))}")

    # 找视频任务
    video_jobs = [j for j in jobs if j["type"] == "video"]
    if not video_jobs:
        print("该章节没有视频任务")
        return

    job = video_jobs[0]
    print(f"\n使用视频任务: {job['name']}")
    print(f"objectid: {job['objectid']}")
    print(f"otherinfo: {job['otherinfo']}")

    # 获取 session cookies
    from api.base import init_session
    _session = init_session()
    session_cookies = _session.cookies

    # 打印脚本生成的参数
    analyze_script_request(course, job, job_info)

    # 用 Playwright 捕获真实浏览器请求
    print("\n" + "=" * 60)
    print("启动 Playwright 浏览器捕获真实请求...")
    print("=" * 60)
    captured = await capture_video_requests(course, job, job_info, session_cookies)

    if captured:
        print(f"\n===== 捕获到 {len(captured)} 个 /multimedia/log/ 请求 =====")
        for i, req in enumerate(captured):
            print(f"\n请求 #{i+1}:")
            print(f"URL: {req['url']}")
    else:
        print("\n未捕获到 /multimedia/log/ 请求!")
        print("可能原因:")
        print("  1. 视频页面需要额外的参数或 cookie")
        print("  2. 视频播放器 JS 未正常加载")
        print("  3. 页面需要通过 knowledge/cards 页面的 iframe 加载")


if __name__ == "__main__":
    asyncio.run(main())
