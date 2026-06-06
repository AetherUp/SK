# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

超星学习通 (Chaoxing) 自动刷课工具。登录后遍历指定课程的章节，自动完成视频、文档、阅读任务，并调用 LLM（DeepSeek）答题提交章节测验。通过 GitHub Actions 定时触发或手动触发运行。

## Running

```bash
# 本地运行（使用 config.ini）
python main.py -c config.ini

# 命令行传参
python main.py -u 手机号 -p 密码 -l 课程ID -a retry

# 常用参数
#   -a retry   遇到未开放章节时回滚重试上一章（推荐，CI 中用）
#   -a continue 跳过未开放章节
#   -a ask     交互式询问（仅本地有 TTY 时可用）
#   -s 2.0     视频播放倍速（最大 2）
```

## Architecture

```
main.py                  # 入口：CLI 解析 → 登录 → 遍历课程/章节
├── api/base.py          # Chaoxing 类：登录、课程列表、视频/文档/测验刷课逻辑
│                         #   study_video → video_progress_log（MD5 加密进度上报）
│                         #   study_work  → 获取题目 → Tiku.query() → 匹配选项 → 提交
├── api/answer.py        # 题库插件系统（Tiku 基类 + 多个实现）
│                         #   Doubao(→ DeepSeek) | AI(OpenAI SDK) | SiliconFlow | TikuYanxi | TikuLike | TikuAdapter
│                         #   通过 config.ini [tiku] provider=ClassName 选择
├── api/decode.py        # 解析超星 HTML 页面（课程列表/章节/任务点/题目）
├── api/cipher.py        # AES-CBC 加密（登录密码加密用）
├── api/captcha.py       # 验证码识别（ddddocr）
├── api/cookies.py       # Cookie 持久化
├── api/logger.py        # loguru 日志
├── api/config.py        # 全局常量（AES Key、UA、Headers）
└── config.ini           # 运行时配置（provider、API key、提交模式等）
```

### 题库插件机制

`api/answer.py` 中所有题库类继承 `Tiku`，通过 `config.ini` 的 `provider=类名` 动态加载。`Tiku.get_tiku_from_config()` 用 `globals()[cls_name]` 实例化。当前使用的 `Doubao` 类实际调用的是 DeepSeek API（`deepseek-chat` 模型），类名保留作历史兼容。

添加新题库只需继承 `Tiku` 并实现 `_query(q_info: dict) -> str` 和 `_init_tiku()`。

### 章节回滚机制

课程章节存在顺序依赖时，需完成前一章的测验才能解锁下一章。`process_course()` 用下标遍历章节列表，通过 `RollBackManager` 控制回滚：

- 遇到 `notOpen` 章节 + `-a retry` → `__point_index -= 1`，强制重处理上一章
- `has_finished` 标记在回滚时 (`rollback_times > 0`) 会被忽略，强制重新拉取任务点
- 同一章节最多回滚 10 次，超限抛出 `MaxRollBackExceeded` 跳过该课程

视频任务遇到 403 时降级为音频模式，两者都失败则跳过该任务点（不影响章节解锁）。

## GitHub Actions

Workflow 位于 `.github/workflows/main.yml`。仓库结构为 `SuperStar-main/` 嵌套在根目录下，workflow 中 `defaults.run.working-directory: ./SuperStar-main` 解决。

- **凭证位置**：workflow 第 49 行，`-u "手机号" -p "密码" -l "课程ID"`，修改账号密码直接改这里
- **API Key**：workflow 动态生成 `config.ini`，`doubao_api_key` 从 `${{ secrets.DEEPSEEK_API_KEY }}` 注入
- **触发**：push 到 main / 每天 UTC 0:00 定时 / workflow_dispatch 手动

## config.ini 关键配置

```ini
[tiku]
provider=Doubao              # 题库类名（Doubao=DeepSeek）
submit=true                  # true=提交答案 false=仅保存
cover_rate=0.8               # 题库覆盖率阈值，低于此值不提交
doubao_endpoint=https://api.deepseek.com/v1/chat/completions
doubao_api_key=sk-xxx        # DeepSeek API key
doubao_model=deepseek-chat   # 模型：deepseek-chat | deepseek-reasoner
doubao_min_interval=1        # API 请求间隔（秒）
```

`config.ini` 在 `.gitignore` 中，本地创建即可，不会被提交。

## Known issues

- **视频 403**：超星服务端 `enc` 加密校验可能变化，失败后会跳过该视频任务点。这是已知的降级策略，通常不影响章节解锁
- **依赖缺失**：`httpx` 在 `requirements.txt` 中未列出但被 `api/answer.py` 的 `AI` 类导入；`pyaes` 需注意 Windows 编译问题
- **GitHub Actions 区域**：超星服务器在国内，GitHub Actions 默认的 `ubuntu-latest`（海外）访问可能较慢或遇到连接问题
