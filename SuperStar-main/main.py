# -*- coding: utf-8 -*-
import argparse
import configparser
import random
import time
import sys
import os
import traceback
from urllib3 import disable_warnings, exceptions

from api.logger import logger
from api.base import Chaoxing, Account
from api.exceptions import LoginError, InputFormatError, MaxRollBackExceeded
from api.answer import Tiku
from api.notification import Notification

# 关闭警告
disable_warnings(exceptions.InsecureRequestWarning)


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="Samueli924/chaoxing",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "-c", "--config", type=str, default=None, help="使用配置文件运行程序"
    )
    parser.add_argument("-u", "--username", type=str, default=None, help="手机号账号")
    parser.add_argument("-p", "--password", type=str, default=None, help="登录密码")
    parser.add_argument(
        "-l", "--list", type=str, default=None, help="要学习的课程ID列表, 以 , 分隔"
    )
    parser.add_argument(
        "-s", "--speed", type=float, default=1.0, help="视频播放倍速 (默认1, 最大2)"
    )
    parser.add_argument(
        "-v",
        "--verbose",
        "--debug",
        action="store_true",
        help="启用调试模式, 输出DEBUG级别日志",
    )
    parser.add_argument(
        "-a", "--notopen-action", type=str, default="retry",
        choices=["retry", "ask", "continue"],
        help="遇到关闭任务点时的行为: retry-重试, ask-询问, continue-继续"
    )
    parser.add_argument(
        "--skip-video", action="store_true",
        help="跳过所有视频任务（视频403无法修复时的兜底方案）"
    )

    # 在解析之前捕获 -h 的行为
    if len(sys.argv) == 2 and sys.argv[1] in {"-h", "--help"}:
        parser.print_help()
        sys.exit(0)

    return parser.parse_args()


def load_config_from_file(config_path):
    """从配置文件加载设置"""
    config = configparser.ConfigParser()
    config.read(config_path, encoding="utf8")
    
    common_config = {}
    tiku_config = {}
    notification_config = {}
    
    # 检查并读取common节
    if config.has_section("common"):
        common_config = dict(config.items("common"))
        # 处理course_list，将字符串转换为列表
        if "course_list" in common_config and common_config["course_list"]:
            common_config["course_list"] = common_config["course_list"].split(",")
        # 处理speed，将字符串转换为浮点数
        if "speed" in common_config:
            common_config["speed"] = float(common_config["speed"])
        # 处理notopen_action，设置默认值为retry
        if "notopen_action" not in common_config:
            common_config["notopen_action"] = "retry"
    
    # 检查并读取tiku节
    if config.has_section("tiku"):
        tiku_config = dict(config.items("tiku"))
        # 处理数值类型转换
        for key in ["delay", "cover_rate"]:
            if key in tiku_config:
                tiku_config[key] = float(tiku_config[key])

    # 检查并读取notification节
    if config.has_section("notification"):
        notification_config = dict(config.items("notification"))
    
    return common_config, tiku_config, notification_config


def build_config_from_args(args):
    """从命令行参数构建配置"""
    common_config = {
        "username": args.username,
        "password": args.password,
        "course_list": args.list.split(",") if args.list else None,
        "speed": args.speed if args.speed else 1.0,
        "notopen_action": args.notopen_action if args.notopen_action else "retry"
    }
    return common_config, {}, {}


def init_config():
    """初始化配置，返回 (common_config, tiku_config, notification_config, skip_video)"""
    args = parse_args()

    if args.config:
        return (*load_config_from_file(args.config), args.skip_video)
    else:
        return (*build_config_from_args(args), args.skip_video)


class RollBackManager:
    """课程回滚管理器，避免无限回滚"""
    def __init__(self):
        self.rollback_times = 0
        self.rollback_id = ""

    def add_times(self, id: str):
        """增加回滚次数"""
        if id == self.rollback_id and self.rollback_times == 10:
            raise MaxRollBackExceeded("回滚次数已达10次, 请手动检查学习通任务点完成情况")
        else:
            self.rollback_times += 1

    def new_job(self, id: str):
        """设置新任务，重置回滚次数"""
        if id != self.rollback_id:
            self.rollback_id = id
            self.rollback_times = 0


def init_chaoxing(common_config, tiku_config):
    """初始化超星实例"""
    username = common_config.get("username", "")
    password = common_config.get("password", "")
    
    # 如果没有提供用户名密码，从命令行获取
    if not username or not password:
        if not sys.stdin.isatty():
            logger.error("未提供用户名和密码，请通过 -u -p 参数传入或配置 GitHub Secrets")
            raise InputFormatError("缺少登录凭证：username 或 password 为空")
        username = input("请输入你的手机号, 按回车确认\n手机号:")
        password = input("请输入你的密码, 按回车确认\n密码:")
    
    account = Account(username, password)
    
    # 设置题库
    tiku = Tiku()
    tiku.config_set(tiku_config)  # 载入配置
    tiku = tiku.get_tiku_from_config()  # 载入题库
    tiku.init_tiku()  # 初始化题库
    
    # 获取查询延迟设置
    query_delay = tiku_config.get("delay", 0)
    
    # 实例化超星API
    chaoxing = Chaoxing(account=account, tiku=tiku, query_delay=query_delay)
    
    return chaoxing


def handle_not_open_chapter(notopen_action, point, tiku, RB, auto_skip_notopen=False):
    """处理未开放章节"""
    if notopen_action == "retry":
        if not tiku or tiku.DISABLE or not tiku.SUBMIT:
            logger.error(
                "章节未开启, 可能由于上一章节的章节检测未完成, 也可能由于该章节因为时效已关闭，"
                "请手动检查完成并提交再重试。或者在配置中配置(自动跳过关闭章节/开启题库并启用提交)"
            )
            return -1
        RB.add_times(point["id"])
        return 0  # 重试上一章节
        
    elif notopen_action == "ask":
        # 询问模式 - 判断是否需要询问
        if not auto_skip_notopen:
            user_choice = input(f"章节 {point['title']} 未开放，是否继续检查后续章节？(y/n): ")
            if user_choice.lower() != 'y':
                # 用户选择停止
                logger.info("根据用户选择停止检查后续章节")
                return -1  # 退出标记
            # 用户选择继续，设置自动跳过标志
            logger.info("用户选择继续检查后续章节，将自动跳过连续的未开放章节")
            return 1, True  # 继续下一章节, 设置自动跳过
        else:
            logger.info(f"章节 {point['title']} 未开放，自动跳过")
            return 1, auto_skip_notopen  # 继续下一章节, 保持自动跳过状态
            
    else:  # notopen_action == "continue"
        # 继续模式，直接跳过当前章节
        logger.info(f"章节 {point['title']} 未开放，根据配置跳过此章节")
        return 1  # 继续下一章节


def process_job(chaoxing, course, job, job_info, speed, skip_video=False):
    """处理单个任务点，返回是否成功"""
    if job["type"] == "video" and skip_video:
        logger.info(f"跳过视频任务: {job['name']}")
        return True
    if job["type"] == "video":
        logger.trace(f"识别到视频任务, 任务章节: {course['title']} 任务ID: {job['jobid']}")
        # 最多重试 3 轮，每轮间隔 60 秒
        for attempt in range(3):
            video_result = chaoxing.study_video(
                course, job, job_info, _speed=speed, _type="Video"
            )
            if chaoxing.StudyResult.is_success(video_result):
                return True
            logger.warning("当前任务非视频任务, 正在尝试音频任务解码")
            video_result = chaoxing.study_video(
                course, job, job_info, _speed=speed, _type="Audio")
            if chaoxing.StudyResult.is_success(video_result):
                return True
            if attempt < 2:
                logger.info(f"视频任务失败，60 秒后重试 ({attempt + 1}/3)")
                time.sleep(60)
        logger.warning(
            f"出现异常任务 -> 任务章节: {course['title']} 任务ID: {job['jobid']}, 3次重试均失败"
        )
        return False
    # 文档任务
    elif job["type"] == "document":
        logger.trace(f"识别到文档任务, 任务章节: {course['title']} 任务ID: {job['jobid']}")
        return chaoxing.study_document(course, job) != chaoxing.StudyResult.ERROR
    # 测验任务
    elif job["type"] == "workid":
        logger.trace(f"识别到章节检测任务, 任务章节: {course['title']}")
        return chaoxing.study_work(course, job, job_info) != chaoxing.StudyResult.ERROR
    # 阅读任务
    elif job["type"] == "read":
        logger.trace(f"识别到阅读任务, 任务章节: {course['title']}")
        chaoxing.strdy_read(course, job, job_info)
    return True


def process_chapter(chaoxing, course, point, RB, notopen_action, speed, auto_skip_notopen=False, skip_video=False):
    """处理单个章节"""
    logger.info(f'当前章节: {point["title"]}')
    
    if point["has_finished"] and RB.rollback_times == 0:
        logger.info(f'章节：{point["title"]} 已完成所有任务点')
        return 1, auto_skip_notopen
    elif point["has_finished"] and RB.rollback_times > 0:
        logger.info(f'章节：{point["title"]} 标记为完成但正在回滚重试，强制重新处理')
    
    # 随机等待，模拟真人节奏：多数较短，偶尔稍长暂停（不超过 2 分钟）
    if random.random() < 0.1:
        sleep_duration = random.uniform(20, 120)   # 10% 概率暂停 20 秒-2 分钟
    else:
        sleep_duration = random.uniform(3, 15)     # 正常间隔 3-15 秒
    logger.debug(f"本次随机等待时间: {sleep_duration:.1f}s")
    time.sleep(sleep_duration)
    
    # 获取当前章节的所有任务点
    jobs = []
    job_info = None
    jobs, job_info = chaoxing.get_job_list(
        course["clazzId"], course["courseId"], course["cpi"], point["id"]
    )

    # 发现未开放章节, 根据配置处理
    try:
        if job_info.get("notOpen", False):
            result = handle_not_open_chapter(
                notopen_action, point, chaoxing.tiku, RB, auto_skip_notopen
            )
            
            if isinstance(result, tuple):
                return result  # 返回继续标志和更新后的auto_skip_notopen
            else:
                return result, auto_skip_notopen
        
        # 遇到开放的章节，重置自动跳过状态
        auto_skip_notopen = False
        RB.new_job(point["id"])

    except MaxRollBackExceeded:
        logger.error("回滚次数已达10次, 请手动检查学习通任务点完成情况")
        # 跳过该课程
        return -1, auto_skip_notopen  # 退出标记
    
    chaoxing.rollback_times = RB.rollback_times
    
    # 可能存在章节无任何内容的情况
    if not jobs:
        if RB.rollback_times > 0:
            logger.trace(f"回滚中 尝试空页面任务, 任务章节: {course['title']}")
            chaoxing.study_emptypage(course, point)
        return 1, auto_skip_notopen  # 继续下一章节
    
    # 遍历所有任务点，记录失败的任务
    has_failure = False
    for job in jobs:
        if not process_job(chaoxing, course, job, job_info, speed, skip_video):
            has_failure = True

    if has_failure:
        logger.info(f'章节 {point["title"]} 有任务未完成，稍后重试')
        return 2, auto_skip_notopen  # 重试当前章节
    return 1, auto_skip_notopen  # 继续下一章节


def process_course(chaoxing, course, notopen_action, speed, skip_video=False):
    """处理单个课程"""
    logger.info(f"开始学习课程: {course['title']}")
    
    # 获取当前课程的所有章节
    point_list = chaoxing.get_course_point(
        course["courseId"], course["clazzId"], course["cpi"]
    )

    total_points = len(point_list["points"])

    __point_index = 0
    auto_skip_notopen = False
    RB = RollBackManager()
    # 追踪：上一章是否已完成且无有效任务（避免空章节死循环回滚）
    prev_was_empty = False

    while __point_index < total_points:
        point = point_list["points"][__point_index]
        finished = sum(1 for p in point_list["points"] if p["has_finished"])
        pct = finished / total_points * 100
        logger.info(f'课程进度: {finished}/{total_points} ({pct:.0f}%)')

        # 如果上一章是已完成空章节，且当前章未开放 → 直接跳过
        if prev_was_empty and point.get("has_finished") == False:
            logger.info(f'章节 {point["title"]} 未开放且前置章节无有效任务，跳过')
            __point_index += 1
            prev_was_empty = False
            continue

        result, auto_skip_notopen = process_chapter(
            chaoxing, course, point, RB, notopen_action, speed, auto_skip_notopen, skip_video
        )

        if result == -1:
            break
        elif result == 0:  # 回滚前一章
            prev_idx = max(0, __point_index - 1)
            prev_point = point_list["points"][prev_idx]
            if prev_point["has_finished"] and RB.rollback_times >= 2:
                prev_was_empty = True
                logger.info(f'前置章节 {prev_point["title"]} 已完成且无有效任务，将在下次跳过')
            __point_index -= 1
        elif result == 2:  # 重试当前章节，不变下标
            logger.info("任务未完成，准备重试当前章节")
            time.sleep(random.uniform(15, 30))
        else:
            prev_was_empty = False
            __point_index += 1


def filter_courses(all_course, course_list):
    """过滤要学习的课程"""
    if not course_list:
        # 手动输入要学习的课程ID列表
        print("*" * 10 + "课程列表" + "*" * 10)
        for course in all_course:
            print(f"ID: {course['courseId']} 课程名: {course['title']}")
        print("*" * 28)
        try:
            course_list = input(
                "请输入想要学习的课程列表,以逗号分隔,例: 2151141,189191,198198\n"
            ).split(",")
        except Exception as e:
            raise InputFormatError("输入格式错误") from e

    # 筛选需要学习的课程
    course_task = []
    for course in all_course:
        if course["courseId"] in course_list:
            course_task.append(course)
    
    # 如果没有指定课程，则学习所有课程
    if not course_task:
        course_task = all_course
    
    return course_task


def main():
    """主程序入口"""
    try:
        # 初始化配置
        common_config, tiku_config, notification_config, skip_video = init_config()
        
        # 规范化播放速度
        speed = min(2.0, max(1.0, common_config.get("speed", 1.0)))
        notopen_action = common_config.get("notopen_action", "retry")
        
        # 初始化超星实例
        chaoxing = init_chaoxing(common_config, tiku_config)
        
        # 设置外部通知
        notification = Notification()
        notification.config_set(notification_config)
        notification = notification.get_notification_from_config()
        notification.init_notification()
        
        _login_state = chaoxing.login()
        if not _login_state["status"]:
            raise LoginError(_login_state["msg"])
        
        # 获取所有的课程列表
        all_course = chaoxing.get_course_list()
        
        # 过滤要学习的课程
        course_task = filter_courses(all_course, common_config.get("course_list"))
        
        # 开始学习
        logger.info(f"课程列表过滤完毕, 当前课程任务数量: {len(course_task)}")
        for course in course_task:
            process_course(chaoxing, course, notopen_action, speed, skip_video)
        
        logger.info("所有课程学习任务已完成")
        notification.send("chaoxing : 所有课程学习任务已完成")
        
    except SystemExit as e:
        if e.code != 0:
            logger.error(f"错误: 程序异常退出, 返回码: {e.code}")
        sys.exit(e.code)
    except KeyboardInterrupt as e:
        logger.error(f"错误: 程序被用户手动中断, {e}")
    except BaseException as e:
        logger.error(f"错误: {type(e).__name__}: {e}")
        logger.error(traceback.format_exc())
        try:
            notification.send(f"chaoxing : 出现错误 {type(e).__name__}: {e}\n{traceback.format_exc()}")
        except Exception:
            pass  # 如果通知发送失败，忽略异常
        raise e


if __name__ == "__main__":
    main()
