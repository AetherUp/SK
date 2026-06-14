# -*- coding: utf-8 -*-
from enum import Enum
from hashlib import md5

import requests
from requests.adapters import HTTPAdapter

from api.answer import *
from api.cipher import AESCipher
from api.config import GlobalConst as gc
from api.cookies import save_cookies, use_cookies
from api.decode import (
    decode_course_list,
    decode_course_point,
    decode_course_card,
    decode_course_folder,
    decode_questions_info,
)
from api.process import show_progress
from api.exceptions import MaxRetryExceeded


def get_timestamp():
    return str(int(time.time() * 1000))


def get_random_seconds():
    # 模拟真实观看行为：多数时间连续看，偶尔长时间暂停
    if random.random() < 0.15:  # 15% 概率模拟走神/暂停
        return random.randint(120, 480)
    return random.randint(45, 180)


def init_session(isVideo: bool = False, isAudio: bool = False):
    _session = requests.session()
    _session.verify = False
    _session.mount("http://", HTTPAdapter(max_retries=3))
    _session.mount("https://", HTTPAdapter(max_retries=3))
    if isVideo:
        _session.headers = gc.VIDEO_HEADERS
    elif isAudio:
        _session.headers = gc.AUDIO_HEADERS
    else:
        _session.headers = gc.HEADERS
    _session.cookies.update(use_cookies())
    return _session


class Account:
    username = None
    password = None
    last_login = None
    isSuccess = None

    def __init__(self, _username, _password):
        self.username = _username
        self.password = _password


class Chaoxing:
    class StudyResult(Enum):
        SUCCESS = 0
        FORBIDDEN = 1  # 403
        ERROR = 2
        TIMEOUT = 3
        CAPTCHA = 4  # 验证码拦截

        @staticmethod
        def is_success(result):
            return result == Chaoxing.StudyResult.SUCCESS

        @staticmethod
        def is_failure(result):
            return result != Chaoxing.StudyResult.SUCCESS

    def __init__(self, account: Account = None, tiku: Tiku = None,**kwargs):
        self.account = account
        self.cipher = AESCipher()
        self.tiku = tiku
        self.kwargs = kwargs
        self.rollback_times = 0

    def login(self):
        _session = requests.session()
        _session.verify = False
        _url = "https://passport2.chaoxing.com/fanyalogin"
        _data = {
            "fid": "-1",
            "uname": self.cipher.encrypt(self.account.username),
            "password": self.cipher.encrypt(self.account.password),
            "refer": "https%3A%2F%2Fi.chaoxing.com",
            "t": True,
            "forbidotherlogin": 0,
            "validate": "",
            "doubleFactorLogin": 0,
            "independentId": 0,
        }
        logger.trace("正在尝试登录...")
        resp = _session.post(_url, headers=gc.HEADERS, data=_data)
        if resp and resp.json()["status"] == True:
            save_cookies(_session)
            logger.info("登录成功...")
            return {"status": True, "msg": "登录成功"}
        else:
            return {"status": False, "msg": str(resp.json()["msg2"])}

    def get_fid(self):
        _session = init_session()
        return _session.cookies.get("fid")

    def get_uid(self):
        _session = init_session()
        return _session.cookies.get("_uid")

    def get_course_list(self):
        _session = init_session()
        _url = "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/courselistdata"
        _data = {"courseType": 1, "courseFolderId": 0, "query": "", "superstarClass": 0}
        logger.trace("正在读取所有的课程列表...")
        # 接口突然抽风, 增加headers
        _headers = {
            "Host": "mooc2-ans.chaoxing.com",
            "sec-ch-ua-platform": '"Windows"',
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
            "Accept": "text/html, */*; q=0.01",
            "sec-ch-ua": '"Microsoft Edge";v="129", "Not=A?Brand";v="8", "Chromium";v="129"',
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "sec-ch-ua-mobile": "?0",
            "Origin": "https://mooc2-ans.chaoxing.com",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Referer": "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/interaction?moocDomain=https://mooc1-1.chaoxing.com/mooc-ans",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6,ja;q=0.5",
        }
        _resp = _session.post(_url, headers=_headers, data=_data)
        # logger.trace(f"原始课程列表内容:\n{_resp.text}")
        logger.info("课程列表读取完毕...")
        course_list = decode_course_list(_resp.text)

        _interaction_url = "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/interaction"
        _interaction_resp = _session.get(_interaction_url)
        course_folder = decode_course_folder(_interaction_resp.text)
        for folder in course_folder:
            _data = {
                "courseType": 1,
                "courseFolderId": folder["id"],
                "query": "",
                "superstarClass": 0,
            }
            _resp = _session.post(_url, data=_data)
            course_list += decode_course_list(_resp.text)
        return course_list

    def get_course_point(self, _courseid, _clazzid, _cpi):
        _session = init_session()
        _url = f"https://mooc2-ans.chaoxing.com/mooc2-ans/mycourse/studentcourse?courseid={_courseid}&clazzid={_clazzid}&cpi={_cpi}&ut=s"
        logger.trace("开始读取课程所有章节...")
        _resp = _session.get(_url)
        logger.info("课程章节读取成功...")
        save_cookies(_session)
        return decode_course_point(_resp.text)

    def get_job_list(self, _clazzid, _courseid, _cpi, _knowledgeid):
        _session = init_session()
        job_list = []
        job_info = {}
        for _possible_num in [
            "0",
            "1",
            "2",
            "3",
            "4",
            "5",
            "6",
        ]:  # 学习界面任务卡片数, 很少有3个的, 但是对于章节解锁任务点少一个都不行, 可以从API /mooc-ans/mycourse/studentstudyAjax获取值, 或者干脆直接加, 但二者都会造成额外的请求
            _url = f"https://mooc1.chaoxing.com/mooc-ans/knowledge/cards?clazzid={_clazzid}&courseid={_courseid}&knowledgeid={_knowledgeid}&num={_possible_num}&ut=s&cpi={_cpi}&v=20160407-3&mooc2=1"
            logger.trace("开始读取章节所有任务点...")
            _resp = _session.get(_url)
            _job_list, _job_info = decode_course_card(_resp.text)
            if _job_info.get("notOpen", False):
                # 直接返回, 节省一次请求
                logger.info("该章节未开放")
                return [], _job_info
            job_list += _job_list
            job_info.update(_job_info)
            # if _job_list and len(_job_list) != 0:
            #     break
        # logger.trace(f"原始任务点列表内容:\n{_resp.text}")
        # 保存 cookie，确保视频请求拿到完整会话
        save_cookies(_session)
        logger.info("章节任务点读取成功...")
        return job_list, job_info

    def _md5enc(self, clazzId, userid, jobid, objectId, value, duration, suffix):
        return md5(
            f"[{clazzId}][{userid}][{jobid}][{objectId}][{value * 1000}][d_yHJ!$pdA~5][{duration * 1000}][{suffix}]".encode()
        ).hexdigest()

    def get_enc(self, clazzId, jobid, objectId, playingTime, duration, userid):
        return self._md5enc(clazzId, userid, jobid, objectId, playingTime, duration, f"0_{duration}")

    def video_progress_log(
        self,
        _session,
        _course,
        _job,
        _job_info,
        _dtoken,
        _duration,
        _playingTime,
        _type: str = "Video",
    ):
        # 浏览器 confirmed: otherInfo 不含 courseId，始终分开传
        _raw_other = _job['otherinfo']
        if 'courseId=' in _raw_other:
            _raw_other = re.sub(r'&?courseId=\d+', '', _raw_other)
        _mid_text = f"otherInfo={_raw_other}&courseId={_course['courseId']}&"
        _uid = self.get_uid()
        _clazzId = _course['clazzId']
        _jobid = _job['jobid']
        _objId = _job['objectid']
        _enc = self.get_enc(_clazzId, _jobid, _objId, _playingTime, _duration, _uid)
        _t = get_timestamp()
        _vfce = self._md5enc(_clazzId, _uid, _jobid, _objId, 0, _duration, "0_0")
        _ade = self._md5enc(_clazzId, _uid, _jobid, _objId, _duration, _duration, f"0_{_duration}")

        _extra = f"videoFaceCaptureEnc={_vfce}&attDuration={_duration}&attDurationEnc={_ade}&courseEngineInfo=false&"

        # 浏览器 verified: isdrag=2，优先尝试
        for _isdrag in ["3", "4", "0", "2"]:
            for _rt in ["0.9", "1"]:
                _url = (
                    f"https://mooc1.chaoxing.com/mooc-ans/multimedia/log/a/"
                    f"{_course['cpi']}/"
                    f"{_dtoken}?"
                    f"clazzId={_course['clazzId']}&"
                    f"playingTime={_playingTime}&"
                    f"duration={_duration}&"
                    f"clipTime=0_{_duration}&"
                    f"objectId={_job['objectid']}&"
                    f"{_mid_text}"
                    f"jobid={_job['jobid']}&"
                    f"userid={_uid}&"
                    f"isdrag={_isdrag}&"
                    f"view=pc&"
                    f"enc={_enc}&"
                    f"rt={_rt}&"
                    f"{_extra}"
                    f"dtype={_type}&"
                    f"_t={_t}"
                )
                # 第一次尝试输出完整 URL 用于对比调试
                if _playingTime == 0 and _isdrag == "2" and _rt == "0.9":
                    logger.info(f"脚本请求URL: {_url}")
                resp = _session.get(_url)
                if resp.status_code == 200:
                    return resp.json(), 200
                elif resp.status_code == 403:
                    logger.warning(f"403响应体: {resp.text[:500]}")
        logger.warning("出现403报错, 尝试修复无效, 正在跳过当前任务点...")
        return {"isPassed": False}, 403
    def study_video(
        self, _course, _job, _job_info, _speed: float = 1.0, _type: str = "Video"
    ) -> StudyResult:
        if _type == "Video":
            _session = init_session(isVideo=True)
        else:
            _session = init_session(isAudio=True)
        _session.headers.update()
        _info_url = f"https://mooc1.chaoxing.com/ananas/status/{_job['objectid']}?k={self.get_fid()}&flag=normal"
        _video_info = _session.get(_info_url).json()
        # 调试：输出完整 video_info 看看有没有 videoFaceCaptureEnc
        logger.debug(f"video_info keys: {list(_video_info.keys())}")
        if _video_info["status"] == "success":
            # 保存 cookie，确保进度上报时有完整会话
            save_cookies(_session)
            _dtoken = _video_info["dtoken"]
            _duration = _video_info["duration"]
            _crc = _video_info["crc"]
            _key = _video_info["key"]
            _isPassed = False
            _isFinished = False
            _playingTime = 0
            logger.info(f"开始任务: {_job['name']}, 总时长: {_duration}秒")
            state = 200
            while not _isFinished:
                if _isFinished:
                    _playingTime = _duration
                _isPassed, state = self.video_progress_log(
                    _session,
                    _course,
                    _job,
                    _job_info,
                    _dtoken,
                    _duration,
                    _playingTime,
                    _type,
                )
                if not _isPassed or (_isPassed and _isPassed.get("isPassed")):
                    break
                if _isPassed and not _isPassed.get("isPassed") and state == 403:
                    if _duration > 0 and _playingTime / _duration > 0.95:
                        logger.info("video 95pct done - treating as success")
                        _isFinished = True
                        break
                    return self.StudyResult.FORBIDDEN
                _wait_time = get_random_seconds()
                if _playingTime + _wait_time >= int(_duration):
                    _wait_time = int(_duration) - _playingTime
                    _isPassed, state = self.video_progress_log(_session, _course, _job, _job_info, _dtoken, _duration, _duration, _type)
                    if _isPassed['isPassed']:
                        _isFinished = True
                # 播放进度条
                show_progress(_job["name"], _playingTime, _wait_time, _duration, _speed)
                _playingTime += _wait_time
            print("\r", end="", flush=True)
            logger.info(f"任务完成: {_job['name']}")
            return self.StudyResult.SUCCESS
        else:
            return self.StudyResult.ERROR
    def study_document(self, _course, _job) -> StudyResult:
        """
        Study a document in Chaoxing platform.

        This method makes a GET request to fetch document information for a given course and job.

        Args:
            _course (dict): Dictionary containing course information with keys:
                - courseId: ID of the course
                - clazzId: ID of the class
            _job (dict): Dictionary containing job information with keys:
                - jobid: ID of the job
                - otherinfo: String containing node information
                - jtoken: Authentication token for the job

        Returns:
            requests.Response: Response object from the GET request

        Note:
            This method requires the following helper functions:
            - init_session(): To initialize a new session
            - get_timestamp(): To get current timestamp
            - re module for regular expression matching
        """
        _session = init_session()
        _url = f"https://mooc1.chaoxing.com/ananas/job/document?jobid={_job['jobid']}&knowledgeid={re.findall(r'nodeId_(.*?)-', _job['otherinfo'])[0]}&courseid={_course['courseId']}&clazzid={_course['clazzId']}&jtoken={_job['jtoken']}&_dc={get_timestamp()}"
        _resp = _session.get(_url)
        if _resp.status_code != 200:
            return self.StudyResult.ERROR
        else:
            return self.StudyResult.SUCCESS

    def study_work(self, _course, _job, _job_info) -> StudyResult:
        if self.tiku.DISABLE or not self.tiku:
            return self.StudyResult.SUCCESS
        _ORIGIN_HTML_CONTENT = ""  # 用于配合输出网页源码, 帮助修复#391错误

        def random_answer(options: str) -> str:
            answer = ""
            if not options:
                return answer

            if q["type"] == "multiple":
                logger.debug(f"当前选项列表[cut前] -> {options}")
                _op_list = multi_cut(options)
                logger.debug(f"当前选项列表[cut后] -> {_op_list}")

                if not _op_list:
                    logger.error(
                        "选项为空, 未能正确提取题目选项信息! 请反馈并提供以上信息"
                    )
                    return answer

                available_options = len(_op_list)
                select_count = 0
        
                # 根据可用选项数量调整可能选择的选项数
                if available_options <= 1:
                    select_count = available_options
                else:
                    max_possible = min(4, available_options)
                    min_possible = min(2, available_options)
            
                    weights_map = {
                        2: [1.0],
                        3: [0.3, 0.7],
                        4: [0.1, 0.5, 0.4],
                        5: [0.1, 0.4, 0.3, 0.2],
                    }
            
                    weights = weights_map.get(max_possible, [0.3, 0.4, 0.3])
                    possible_counts = list(range(min_possible, max_possible + 1))
            
                    weights = weights[:len(possible_counts)]
            
                    weights_sum = sum(weights)
                    if weights_sum > 0:
                        weights = [w/weights_sum for w in weights]
                
                    select_count = random.choices(possible_counts, weights=weights, k=1)[0]

                selected_options = random.sample(_op_list, select_count) if select_count > 0 else []

                for option in selected_options:
                    answer += option[:1]  # 取首字为答案，例如A或B

                answer = "".join(sorted(answer))
            elif q["type"] == "single":
                answer = random.choice(options.split("\n"))[
                    :1
                ]  # 取首字为答案, 例如A或B
            # 判断题处理
            elif q["type"] == "judgement":
                # answer = self.tiku.jugement_select(_answer)
                answer = "true" if random.choice([True, False]) else "false"
            logger.info(f"随机选择 -> {answer}")
            return answer

        def multi_cut(answer: str):
            """
            将多选题答案字符串按特定字符进行切割, 并返回切割后的答案列表

            参数:
            answer(str): 多选题答案字符串.

            返回:
            list[str]: 切割后的答案列表, 如果无法切割, 则返回默认的选项列表None

            注意:
            如果无法从网页中提取题目信息, 将记录警告日志并返回None
            """
            # cut_char = [',','，','|','\n','\r','\t','#','*','-','_','+','@','~','/','\\','.','&',' ']    # 多选答案切割符
            # ',' 在常规被正确划分的, 选项中出现, 导致 multi_cut 无法正确划分选项 #391
            # IndexError: Cannot choose from an empty sequence #391
            # 同时为了避免没有考虑到的 case, 应该先按照 '\n' 匹配, 匹配不到再按照其他字符匹配
            cut_char = [
                "\n",
                ",",
                "，",
                "|",
                "\r",
                "\t",
                "#",
                "*",
                "-",
                "_",
                "+",
                "@",
                "~",
                "/",
                "\\",
                ".",
                "&",
                " ",
                "、",
            ]  # 多选答案切割符
            res = cut(answer)
            if res is None:
                logger.warning(
                    f"未能从网页中提取题目信息, 以下为相关信息：\n\t{answer}\n\n{_ORIGIN_HTML_CONTENT}\n"
                )  # 尝试输出网页内容和选项信息
                logger.warning("未能正确提取题目选项信息! 请反馈并提供以上信息")
                return None
            else:
                return res

        def clean_res(res):
            cleaned_res = []
            if isinstance(res, str):
                res = [res]
            for c in res:
                cleaned_res.append(re.sub(r'^[A-Za-z]|[.,!?;:，。！？；：]', '', c))

            return cleaned_res

        def is_subsequence(a, o):
            iter_o = iter(o)
            return all(c in iter_o for c in a)

        def with_retry(max_retries=3, delay=1):
            def decorator(func):
                def wrapper(*args, **kwargs):
                    retries = 0
                    while retries < max_retries:
                        try:
                            _resp = func(*args, **kwargs)
                            
                            # 未创建完成该测验则不进行答题，目前遇到的情况是未创建完成等同于没题目
                            if '教师未创建完成该测验' in _resp.text:
                                raise PermissionError("教师未创建完成该测验")

                            questions = decode_questions_info(_resp.text)
                    
                            if _resp.status_code == 200 and questions.get("questions"):
                                return (_resp, questions)
                    
                            logger.warning(f"无效响应 (Code: {getattr(_resp, 'status_code', 'Unknown')}), 重试中... ({retries+1}/{max_retries})")
                
                        except requests.exceptions.RequestException as e:
                            logger.warning(f"请求失败: {str(e)[:50]}, 重试中... ({retries+1}/{max_retries})")
                        retries += 1
                        time.sleep(delay * (2 ** retries))
                    raise MaxRetryExceeded(f"超过最大重试次数 ({max_retries})")
                return wrapper
            return decorator

        # 学习通这里根据参数差异能重定向至两个不同接口, 需要定向至https://mooc1.chaoxing.com/mooc-ans/workHandle/handle
        _session = init_session()
        headers = {
            "Host": "mooc1.chaoxing.com",
            "sec-ch-ua": '"Microsoft Edge";v="129", "Not=A?Brand";v="8", "Chromium";v="129"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Dest": "iframe",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6,ja;q=0.5",
        }
        cookies = _session.cookies.get_dict()

        _url = "https://mooc1.chaoxing.com/mooc-ans/api/work"

        @with_retry(max_retries=3, delay=1)
        def fetch_response():
            return requests.get(
                    _url,
                    headers=headers,
                    cookies=cookies,
                    verify=False,
                    params={
                        "api": "1",
                        "workId": _job["jobid"].replace("work-", ""),
                        "jobid": _job["jobid"],
                        "originJobId": _job["jobid"],
                        "needRedirect": "true",
                        "skipHeader": "true",
                        "knowledgeid": str(_job_info["knowledgeid"]),
                        "ktoken": _job_info["ktoken"],
                        "cpi": _job_info["cpi"],
                        "ut": "s",
                        "clazzId": _course["clazzId"],
                        "type": "",
                        "enc": _job["enc"],
                        "mooc2": "1",
                        "courseid": _course["courseId"],
                    }
            )

        final_resp = {}
        questions = {}

        try:
            final_resp, questions = fetch_response()
        except Exception as e:
            logger.error(f"请求失败: {e}")
            return self.StudyResult.ERROR
        
        _ORIGIN_HTML_CONTENT = final_resp.text  # 用于配合输出网页源码, 帮助修复#391错误

        # 搜题
        total_questions = len(questions["questions"])
        found_answers = 0
        for q in questions["questions"]:
            logger.debug(f"当前题目信息 -> {q}")
            # 添加搜题延迟 #428 - 默认0s延迟
            query_delay = self.kwargs.get("query_delay",0)
            time.sleep(query_delay)
            res = self.tiku.query(q)
            answer = ""
            if not res:
                # 随机答题
                answer = random_answer(q["options"])
                q[f'answerSource{q["id"]}'] = "random"
            else:
                # ---- 快速路径：LLM 直接输出了字母 ----
                if q["type"] == "single" and len(res) == 1 and res.isalpha():
                    answer = res.upper()
                elif q["type"] == "multiple" and re.fullmatch(r'[A-Fa-f]{2,}', res):
                    answer = "".join(sorted(res.upper()))
                elif q["type"] == "judgement" and res in ("对", "错"):
                    answer = "true" if res == "对" else "false"
                # ---- 退化路径：LLM 输出文本，走原有子序列匹配 ----
                elif q["type"] == "multiple":
                    options_list = multi_cut(q["options"])
                    res_list = multi_cut(res)
                    if res_list is not None and options_list is not None:
                        for _a in clean_res(res_list):
                            for o in options_list:
                                if is_subsequence(_a, o):
                                    answer += o[:1]
                        answer = "".join(sorted(answer))
                elif q["type"] == "single":
                    options_list = multi_cut(q["options"])
                    if options_list is not None:
                        t_res = clean_res(res)
                        if t_res:
                            for o in options_list:
                                if is_subsequence(t_res[0], o):
                                    answer = o[:1]
                                    break
                elif q["type"] == "judgement":
                    answer = "true" if self.tiku.judgement_select(res) else "false"
                elif q["type"] == "completion":
                    answer = res if isinstance(res, str) else "".join(res) if isinstance(res, list) else str(res)
                else:
                    answer = res

                if not answer:  # 检查 answer 是否为空
                    logger.warning(f"找到答案但答案未能匹配 -> {res}\t随机选择答案")
                    answer = random_answer(q["options"])  # 如果为空，则随机选择答案
                    q[f'answerSource{q["id"]}'] = "random"
                else:
                    logger.info(f"成功获取到答案：{answer}")
                    q[f'answerSource{q["id"]}'] = "cover"
                    found_answers += 1
            # 填充答案
            q["answerField"][f'answer{q["id"]}'] = answer
            logger.info(f'{q["title"]} 填写答案为 {answer}')
        # 防检测：题库数≥4 题时随机答错 1 题，模拟真人
        # 前提：答错后覆盖率仍不低于 COVER_RATE 阈值，避免只保存不提交卡死后续章节
        if total_questions >= 4 and found_answers >= 3 and random.random() < 0.3:
            covered = [q for q in questions["questions"] if q.get(f'answerSource{q["id"]}') == "cover"]
            if covered:
                _after_found = found_answers - 1
                _after_rate = _after_found / total_questions
                if _after_rate >= self.tiku.COVER_RATE or self.rollback_times >= 1:
                    victim = random.choice(covered)
                    wrong = random_answer(victim["options"])
                    if wrong:
                        victim["answerField"][f'answer{victim["id"]}'] = wrong
                        victim[f'answerSource{victim["id"]}'] = "random"
                        found_answers = _after_found
                        logger.info(f"防检测：故意答错 [{victim['title'][:20]}] -> {wrong}")
                else:
                    logger.info(f"防检测跳过：答错后覆盖率 {_after_rate:.0%} 低于阈值 {self.tiku.COVER_RATE:.0%}")

        cover_rate = (found_answers / total_questions) * 100
        logger.info(f"章节检测题库覆盖率： {cover_rate:.0f}%")
        # 提交模式  现在与题库绑定,留空直接提交, 1保存但不提交
        if self.tiku.get_submit_params() == "1":
            questions["pyFlag"] = "1"
        elif cover_rate >= self.tiku.COVER_RATE*100 or self.rollback_times >= 1:
            questions["pyFlag"] = ""
        else:
            questions["pyFlag"] = "1"
            logger.info(f"章节检测题库覆盖率低于{self.tiku.COVER_RATE*100:.0f}%，不予提交")
        # 组建提交表单
        if questions["pyFlag"] == "1":
            for q in questions["questions"]:
                questions.update(
                    {
                        f'answer{q["id"]}':
                            q["answerField"][f'answer{q["id"]}'] if q[f'answerSource{q["id"]}'] == "cover" else '',
                        f'answertype{q["id"]}': q["answerField"][f'answertype{q["id"]}'],
                    }
                )
        else:
            for q in questions["questions"]:
                questions.update(
                    {
                        f'answer{q["id"]}': q["answerField"][f'answer{q["id"]}'],
                        f'answertype{q["id"]}': q["answerField"][f'answertype{q["id"]}'],
                    }
                )

        del questions["questions"]

        res = _session.post(
            "https://mooc1.chaoxing.com/mooc-ans/work/addStudentWorkNew",
            data=questions,
            headers={
                "Host": "mooc1.chaoxing.com",
                "sec-ch-ua-platform": '"Windows"',
                "X-Requested-With": "XMLHttpRequest",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "sec-ch-ua": '"Microsoft Edge";v="129", "Not=A?Brand";v="8", "Chromium";v="129"',
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "sec-ch-ua-mobile": "?0",
                "Origin": "https://mooc1.chaoxing.com",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Dest": "empty",
                # "Referer": "https://mooc1.chaoxing.com/mooc-ans/work/doHomeWorkNew?courseId=246831735&workAnswerId=52680423&workId=37778125&api=1&knowledgeid=913820156&classId=107515845&oldWorkId=07647c38d8de4c648a9277c5bed7075a&jobid=work-07647c38d8de4c648a9277c5bed7075a&type=&isphone=false&submit=false&enc=1d826aab06d44a1198fc983ed3d243b1&cpi=338350298&mooc2=1&skipHeader=true&originJobId=work-07647c38d8de4c648a9277c5bed7075a",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6,ja;q=0.5",
            },
        )
        if res.status_code == 200:
            # 检查是否是验证码页面（即使返回 200，也可能内容为 HTML）
            if '<html' in res.text and '验证码' in res.text:
                logger.error("答题提交触发验证码拦截 [9010]")
                return self.StudyResult.CAPTCHA
            try:
                res_json = res.json()
            except Exception:
                logger.error(f'提交答题返回异常内容 -> {res.text[:300]}')
                return self.StudyResult.ERROR
            if res_json["status"]:
                logger.info(f'{"提交" if questions["pyFlag"] == "" else "保存"}答题成功 -> {res_json["msg"]}')
            else:
                logger.error(f'{"提交" if questions["pyFlag"] == "" else "保存"}答题失败 -> {res_json["msg"]}')
                return self.StudyResult.ERROR
        else:
            # 非 200 响应也可能是验证码
            if '验证码' in res.text or '操作异常' in res.text:
                logger.error("答题提交触发验证码拦截 [9010]")
                return self.StudyResult.CAPTCHA
            logger.error(f'{"提交" if questions["pyFlag"] == "" else "保存"}答题失败 -> {res.text[:500]}')
            return self.StudyResult.ERROR
        return self.StudyResult.SUCCESS

    def strdy_read(self, _course, _job, _job_info) -> StudyResult:
        """
        阅读任务学习, 仅完成任务点, 并不增长时长
        """
        _session = init_session()
        _resp = _session.get(
            url="https://mooc1.chaoxing.com/ananas/job/readv2",
            params={
                "jobid": _job["jobid"],
                "knowledgeid": _job_info["knowledgeid"],
                "jtoken": _job["jtoken"],
                "courseid": _course["courseId"],
                "clazzid": _course["clazzId"],
            },
        )
        if _resp.status_code != 200:
            logger.error(f"阅读任务学习失败 -> [{_resp.status_code}]{_resp.text}")
            return self.StudyResult.ERROR
        else:
            _resp_json = _resp.json()
            logger.info(f"阅读任务学习 -> {_resp_json['msg']}")
            return self.StudyResult.SUCCESS

    def study_emptypage(self, _course, _chapterId):
        _session = init_session()
        # &cpi=0&verificationcode=&mooc2=1&microTopicId=0&editorPreview=0
        _resp = _session.get(
            url="https://mooc1.chaoxing.com/mooc-ans/mycourse/studentstudyAjax",
            params={
                "courseId": _course["courseId"],
                "clazzid": _course["clazzId"],
                "chapterId": _chapterId['id'],
                "cpi": 0,
                "verificationcode": "",
                "mooc2": 1,
                "microTopicId": 0,
                "editorPreview": 0,
            },
        )
        if _resp.status_code != 200:
            logger.error(f"空页面任务失败 -> [{_resp.status_code}]{_chapterId['title']}")
            return self.StudyResult.ERROR
        else:
            logger.info(f"空页面任务完成 -> {_chapterId['title']}")
            return self.StudyResult.SUCCESS