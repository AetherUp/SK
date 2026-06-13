# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

超星学习通 (Chaoxing) 自动刷课工具。遍历课程章节，自动完成视频/文档/阅读/测验任务。测验通过 DeepSeek V4 Flash 答题提交。**视频任务使用 Playwright 真实浏览器播放，彻底解决 403 问题。**

## Running

```bash
# 本地 — 多账号交互模式（推荐）
python main.py -c config.ini

# 本地 — 指定账号分组
python main.py -c config.ini --profile 账号1

# 本地 — 命令行直接传参
python main.py -u 手机号 -p 密码 -l 课程ID -a retry

# 禁用 Playwright 视频（回退到传统 HTTP 方式）
python main.py -c config.ini --no-playwright-video
```

## Multi-account profiles

`config.ini` 支持多个账号分组，`[common]` 存放默认值，`[account:名称]` 覆盖：

```ini
[common]
username =
password =
course_list =
speed = 1
notopen_action = retry

[account:张三]
username = 13800138000
password = xxx
course_list = 264391804

[account:李四]
username = 13900139000
password = xxx
course_list = 123456
```

- `--profile 张三` 指定分组
- 不加 `--profile` 时自动列出所有分组交互选择
- CLI 参数 `-u -p -l` 优先于配置文件

## Architecture

```
main.py                  # 入口：CLI → 登录 → 遍历课程/章节
api/base.py              # Chaoxing 类：视频/文档/测验/阅读全部业务逻辑
                         #   study_video → video_progress_log（MD5 签名上报）
                         #   study_work → 获取题目 → Tiku.query() → 匹配 → 提交
api/playwright_video.py  # Playwright 视频播放：真实浏览器，零 403
api/answer.py            # 题库插件 (Tiku 基类 + Doubao/AI/SiliconFlow/TikuYanxi/...)
                         #   provider=Doubao → DeepSeek v4-flash（极简模式）
api/decode.py            # BeautifulSoup 解析超星 HTML
api/cipher.py            # pyaes AES-CBC 密码加密
api/captcha.py           # ddddocr 验证码识别
api/logger.py            # loguru
```

## Playwright 视频播放（403 修复）

`api/playwright_video.py` 使用 Chromium 真实浏览器打开超星视频页面，页面 JS 自动处理 MD5 加密和进度上报，完全绕过 403 问题。

- 默认启用，可通过 `--no-playwright-video` 禁用
- Playwright 失败时自动回退到 HTTP 方式
- GitHub Actions 需运行 `playwright install chromium`
- 本地需要 Playwright 和 Chromium 浏览器

## DeepSeek 调用（Doubao 类，answer.py）

**极简模式**，围绕最低成本设计：

| 参数 | 值 | 说明 |
|------|-----|------|
| model | `deepseek-chat` | 内部路由 v4-flash |
| temperature | 0 | 确定性输出 |
| max_tokens | 10 | 答案仅 1-3 字符 |
| system prompt | 34 字符统一固定 | 所有题型共用，缓存命中近 100% |
| 输出格式 | 直接字母 / "对""错" | 不再输出 JSON |

答案匹配双路径（base.py）：单字母直接取 → 多字母排序 → 对/错映射 → 退化文本子序列匹配。

## 章节回滚

`-a retry` 模式下，遇到未开放章节时 `__point_index -= 1` 回退重处理上一章。`has_finished` 在回滚时被忽略，强制重新拉取任务点。同章节最多回滚 10 次，超限跳过该课程。

## 防检测机制

- **视频间隔**（base.py）：45-180 秒，15% 概率长暂停 2-8 分钟
- **章节间隔**（main.py）：3-15 秒，10% 概率长暂停 2-10 分钟
- **测验**（base.py）：≥4 题时 30% 概率故意答错 1 题

## GitHub Actions

Workflow `.github/workflows/main.yml`，仅 `workflow_dispatch` 手动触发。

- **API Key**：`${{ secrets.DEEPSEEK_API_KEY }}` 从 Secret 注入
- **账号密码**：workflow 中直接填写 `-u "手机号" -p "密码" -l "课程ID"`
- **config.ini** 运行时动态生成，仓库里的仅作本地模板
- 工作流已包含 `playwright install chromium` 步骤

## config.ini

```ini
[common]
username =            # 多账号时留空，或用 --profile 指定
password =            #
course_list =         #
speed = 1
notopen_action = retry

[account:账号1]       # 多账号分组（可选）
username = 手机号
password = 密码
course_list = 课程ID

[tiku]
provider=Doubao
submit=true
cover_rate=0.8
deepseek_endpoint=https://api.deepseek.com/v1/chat/completions
deepseek_api_key=
deepseek_model=deepseek-chat
deepseek_min_interval=1
```
