# -*- coding: utf-8 -*-
"""端到端测试：验证 Playwright 视频模块集成"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api.base import Chaoxing, Account
from api.answer import Tiku
from api.playwright_video import study_video_playwright

# 登录
account = Account("13975076819", "Lzz20070613")
chaoxing = Chaoxing(account=account, tiku=Tiku())
result = chaoxing.login()
if not result["status"]:
    print(f"登录失败: {result['msg']}")
    sys.exit(1)
print("登录成功!")

# 获取课程
courses = chaoxing.get_course_list()
course = None
for c in courses:
    if c["courseId"] == "264391804":
        course = c
        break
if not course:
    print("未找到课程")
    sys.exit(1)

# 获取章节
points_data = chaoxing.get_course_point(course["courseId"], course["clazzId"], course["cpi"])
points = points_data["points"]

# 找未完成的章节
target = None
for p in points:
    if not p["has_finished"]:
        target = p
        break
if not target:
    print("所有章节已完成")
    sys.exit(0)

print(f"章节: {target['title']}")

# 获取任务点
jobs, job_info = chaoxing.get_job_list(
    course["clazzId"], course["courseId"], course["cpi"], target["id"]
)

video_jobs = [j for j in jobs if j["type"] == "video"]
if not video_jobs:
    print("无视频任务")
    sys.exit(0)

job = video_jobs[0]
print(f"视频: {job['name']}")
print(f"objectid: {job['objectid']}")

# 使用 Playwright 播放
print("\n开始 Playwright 视频播放...")
success = study_video_playwright(course, job, job_info, speed=1.0)

if success:
    print("\n[SUCCESS] Playwright 视频播放成功!")
else:
    print("\n[FAILED] Playwright 视频播放失败")

print("\n请检查超星平台确认视频是否标记为已完成")
