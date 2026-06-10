# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

超星学习通 (Chaoxing) 自动刷课工具。遍历课程章节，自动完成视频/文档/阅读/测验任务。测验通过 DeepSeek V4 Flash 答题提交。GitHub Actions 仅保留手动触发。

## Running

```bash
# 本地（config.ini 填写 [common] 段的 username/password/course_list）
python main.py -c config.ini

# 或命令行传参
python main.py -u 手机号 -p 密码 -l 课程ID -a retry

# -a retry: 未开放章节回滚重试  -a continue: 跳过  -s 倍速(最大2)
```

## Architecture

```
main.py                  # 入口：CLI → 登录 → 遍历课程/章节
api/base.py              # Chaoxing 类：视频/文档/测验/阅读全部业务逻辑
                         #   study_video → video_progress_log（MD5 签名上报）
                         #   study_work → 获取题目 → Tiku.query() → 匹配 → 提交
api/answer.py            # 题库插件 (Tiku 基类 + Doubao/AI/SiliconFlow/TikuYanxi/...)
                         #   provider=Doubao → DeepSeek v4-flash（极简模式）
api/decode.py            # BeautifulSoup 解析超星 HTML
api/cipher.py            # pyaes AES-CBC 密码加密
api/captcha.py           # ddddocr 验证码识别
api/logger.py            # loguru
```

## DeepSeek 调用（Doubao 类，answer.py:622-682）

**极简模式**，围绕最低成本设计：

| 参数 | 值 | 说明 |
|------|-----|------|
| model | `deepseek-chat` | 内部路由 v4-flash |
| temperature | 0 | 确定性输出 |
| max_tokens | 10 | 答案仅 1-3 字符 |
| system prompt | 34 字符统一固定 | 所有题型共用，缓存命中近 100% |
| 输出格式 | 直接字母 / "对""错" | 不再输出 JSON |

答案匹配双路径（base.py:551-582）：单字母直接取 → 多字母排序 → 对/错映射 → 退化文本子序列匹配。

## 章节回滚

`-a retry` 模式下，遇到未开放章节时 `__point_index -= 1` 回退重处理上一章。`has_finished` 在回滚时被忽略，强制重新拉取任务点。同章节最多回滚 10 次，超限跳过该课程。

## 防检测机制

- **视频间隔**（base.py:27-30）：45-180 秒，15% 概率长暂停 2-8 分钟
- **章节间隔**（main.py:246-250）：3-15 秒，10% 概率长暂停 2-10 分钟
- **测验**（base.py:598-607）：≥4 题时 30% 概率故意答错 1 题

## GitHub Actions

Workflow `.github/workflows/main.yml`，仅 `workflow_dispatch` 手动触发（push/schedule 已注释）。

- **账号密码**：workflow 第 49 行 `-u "手机号" -p "密码" -l "课程ID"`
- **API Key**：workflow 第 43 行 `${{ secrets.DEEPSEEK_API_KEY }}`，运行时从 Secret 注入
- **config.ini** 动态生成，仓库里的仅作本地模板（key 留空）

## config.ini

```ini
[common]
username =            # 本地填
password =            # 本地填
course_list =         # 本地填，如 264391804
speed = 1

[tiku]
provider=Doubao
submit=true
cover_rate=0.8
deepseek_endpoint=https://api.deepseek.com/v1/chat/completions
deepseek_api_key=       # 本地填，Actions 从 Secret 注入
deepseek_model=deepseek-chat
deepseek_min_interval=1
```

## Known issues

- **视频 403**：超星 enc 签名可能变化，失败后降级音频 → 仍失败则跳过
- **数据中心 IP**：GitHub Actions 海外 IP 可能被超星标记，进度被重置时考虑本地跑
- `config.ini` 在 `.gitignore` 中，`git add -f` 才能强制推送
