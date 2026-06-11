# -*- coding: utf-8 -*-
class GlobalConst:
    AESKey = "u2oh6Vu^HWe4_AES"
    _BROWSER_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36 Edg/149.0.0.0",
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Sec-Ch-Ua": '"Microsoft Edge";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }
    HEADERS = _BROWSER_HEADERS
    COOKIES_PATH = "cookies.txt"
    VIDEO_HEADERS = {**_BROWSER_HEADERS,
        "Referer": "https://mooc1.chaoxing.com/ananas/modules/video/index.html?v=2026-0604-1025",
        "Host": "mooc1.chaoxing.com",
    }
    AUDIO_HEADERS = {**_BROWSER_HEADERS,
        "Referer": "https://mooc1.chaoxing.com/ananas/modules/audio/index_new.html?v=2026-0604-1025",
        "Host": "mooc1.chaoxing.com",
    }
    THRESHOLD = 3
