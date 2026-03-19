# ai-safety-bot（AI 安全日报机器人）

每天定时抓取 **RSS/Atom + 少量白名单页面（html_list）**，用**标题关键词规则**筛出 AI 安全相关内容，生成适合飞书 **text** 消息的纯文本日报并推送。

## 当前能力（与代码一致）
- **信息源**
  - `feed`：RSS/Atom 抓取（主干）
  - `html_list`：固定白名单页面抓取（路线 B；非全站搜索）
- **筛选与输出**
  - 标题关键词相关性筛选（`configs/rules.yaml`）
  - 摘要：从 feed 的 summary/description 或 html 页面 meta/JSON-LD 中提取（尽力而为）
  - 输出：飞书 **text** 消息（不渲染 Markdown，因此正文是纯文本排版）
- **运行与健壮性**
  - 单个信息源抓取/解析失败不影响整体
  - `feed`：发布时间不可解析直接丢弃（并打日志）
  - `feed`：最近 N 天过滤（默认 30 天）
- **避免重复推送**
  - `data/sent_items.json` 记录已推送条目（保留 90 天）
  - 推送成功后自动更新并由 GitHub Actions 自动 commit/push 回 `main`

## 配置文件
- 信息源：`configs/sources.yaml`
- 筛选规则：`configs/rules.yaml`

关键参数（`configs/rules.yaml`）：
- `relevance.recency_days`：`feed` 最近 N 天过滤（默认 30）
- `output.summary_max_chars`：摘要截断长度（默认 160）

## 本地运行

### 环境要求
- Python 3.11+

### 安装依赖

```bash
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 设置环境变量（飞书）
- 必填：`FEISHU_WEBHOOK_URL`
- 可选：`FEISHU_BOT_SECRET`（开启飞书机器人“签名校验”时必填）

PowerShell 示例：

```powershell
$env:FEISHU_WEBHOOK_URL="https://open.feishu.cn/open-apis/bot/v2/hook/xxxx"
$env:FEISHU_BOT_SECRET="your-feishu-bot-secret"
```

### 运行

```bash
python -m src.main
```

运行后会：
- 推送一条飞书 text 消息
- 生成调试产物：`outputs/daily_latest.md`

## html_list（路线 B：白名单页面抓取）
- `type: "html_list"` 只抓取**配置里写死的页面**，不做全站搜索。
- 当前实现是“轻量增强解析”：
  - ModelScope Learn：尽量从列表页提取多条链接及各自标题/日期/简要摘要
  - Volcengine/Ant Group：即使是单页也尽量从 meta/JSON-LD 提取更好的标题/摘要/日期
- 解析失败只会记录日志并跳过该源，不影响其他信息源。

## 去重与已推送记录（避免重复推送）
- 状态文件：`data/sent_items.json`
- 唯一 ID：
  - 优先：`source + normalized_url`
  - 无 URL 兜底：`source + title + published_at`
- 只保留最近 90 天记录（自动清理）。
- 只有“飞书推送成功”后才会写入记录，避免误标记为已发。

## GitHub Actions（定时运行）
- 工作流：`.github/workflows/daily.yml`
- 触发：
  - `workflow_dispatch`：手动触发（用于调试）
  - `schedule`：北京时间 **09:07**（UTC `01:07`）
- Secrets（仓库 Settings → Secrets and variables → Actions）：
  - `FEISHU_WEBHOOK_URL`（必填）
  - `FEISHU_BOT_SECRET`（可选）
- 推送成功后：若 `data/sent_items.json` 有变化，会自动 commit 并 push 回 `main`


