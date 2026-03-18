# ai-safety-daily-bot（第一版 MVP）

目标：每天定时抓取少量高质量 RSS/Atom 信息源，基于**标题**做 AI 安全相关性筛选，生成中文 Markdown 日报，并通过飞书机器人 Webhook 推送。

第一版范围（MVP）：
- ✅ RSS/Atom 抓取（2–3 个稳定源，含可选候选源）
- ✅ 标题关键词相关性筛选
- ✅ 中文 Markdown 日报
- ✅ 飞书 Webhook 推送
- ✅ GitHub Actions 定时运行
- ❌ 不做：LLM 摘要、Server酱、复杂去重、HTML 列表页解析、GitHub/HF 全站搜索、自动提交产物、飞书卡片

## 本地运行

### 1) 环境要求
- Python 3.11+

### 2) 安装依赖

```bash
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3) 配置
- 信息源：`configs/sources.yaml`
- 筛选规则：`configs/rules.yaml`

#### 规则说明（与 `configs/rules.yaml` 对应）
- **最近 30 天过滤**：由 `relevance.recency_days` 控制；只有能解析出发布时间的条目才会参与筛选，无法解析日期的条目会被直接丢弃并在日志中提示。
- **摘要长度**：由 `output.summary_max_chars` 控制；日报中展示的 `摘要` 会按该长度截断。

### 4) 设置环境变量（飞书）
需要配置飞书自定义机器人 Webhook，支持可选的“签名校验”：

- 必填：`FEISHU_WEBHOOK_URL` — 飞书自定义机器人 Webhook 地址
- 可选：`FEISHU_BOT_SECRET` — 若你的机器人开启了“签名校验”，请在此填写 Secret

PowerShell 示例：

```powershell
$env:FEISHU_WEBHOOK_URL="https://open.feishu.cn/open-apis/bot/v2/hook/xxxx"
# 若开启签名校验，还需设置：
$env:FEISHU_BOT_SECRET="your-feishu-bot-secret"
```

### 5) 运行

```bash
python -m src.main
```

成功后会：
- 在控制台打印抓取与筛选统计
- 向飞书推送当日 Markdown 日报
- 在 `outputs/daily_latest.md` 写入最近一次生成的日报（便于排查）

#### 开启“签名校验”的说明
1. 在飞书群里添加“自定义机器人”，勾选“签名校验”并复制 Secret
2. 在本地/Actions 中设置 `FEISHU_BOT_SECRET`
3. 本项目会自动按照飞书要求生成 `timestamp` 与 `sign` 并附加到请求体
4. 未配置 `FEISHU_BOT_SECRET` 时将直接发送（兼容未启用签名的机器人）

## 信息源说明（第一版）
- 默认启用：`Google Security Blog`、`GitHub Blog Security`
- 候选但默认关闭：`OpenAI News`（需你本地验证抓取成功后再打开 `enabled: true`）

## GitHub Actions 配置（定时运行）

### 1) 配置 Secrets
在 GitHub 仓库中进入：
`Settings -> Secrets and variables -> Actions -> New repository secret`

新增（Secrets → Actions）：
- `FEISHU_WEBHOOK_URL`（必填）
- `FEISHU_BOT_SECRET`（可选，启用签名校验时必须配置）

### 2) 工作流
工作流文件位于：`.github/workflows/daily.yml`
- 支持 `schedule`（定时）和 `workflow_dispatch`（手动）触发

## 常见问题（MVP 约定）
- 某个 RSS 源抓取失败：只会跳过该源并记录错误日志，不影响其他源与最终推送。
- 筛选后没有条目：仍会生成“今日高相关动态较少”的日报并推送。

