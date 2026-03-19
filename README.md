# ai-safety-bot（AI 安全日报机器人）

每天定时抓取 **RSS/Atom + 少量白名单页面（html_list）**，用**标题关键词规则**筛出 AI 安全相关内容，生成适合飞书 **text** 消息的纯文本日报并推送。

## 当前能力（与代码一致）
- **信息源**
  - `feed`：RSS/Atom 抓取（主干）
  - `html_list`：固定白名单页面抓取（路线 B；非全站搜索，当前全部暂停）
- **筛选与输出**
  - 标题关键词相关性筛选（`configs/rules.yaml`）
  - 摘要：从 feed 的 summary/description 或 html 页面 meta/JSON-LD 中提取（尽力而为）
  - 输出：飞书 **text** 消息（不渲染 Markdown，因此正文是纯文本排版）
- **运行与健壮性**
  - 单个信息源抓取/解析失败不影响整体
  - `feed`：发布时间不可解析直接丢弃（并打日志）
  - `feed`：最近 N 天过滤（当前 **180 天**）
- **避免重复推送**
  - `data/sent_items.json` 记录已推送条目（保留 90 天）
  - 推送成功后自动更新并由 GitHub Actions 自动 commit/push 回 `main`

## 当前启用的信息源

| 名称 | 类型 | 分类 | 说明 |
|---|---|---|---|
| Google Security Blog | feed | 安全研究/社区 | Google 官方安全博客 |
| GitHub Blog Security | feed | GitHub/开源生态 | GitHub 安全栏目，含供应链、AI coding 安全 |
| OpenAI News | feed | 国外大厂 | OpenAI 官方 News RSS，重点关注 safety/policy |
| Hugging Face Blog | feed | HF/开源生态 | HF 官方博客，噪声较大，依赖关键词过滤 |
| arXiv cs.CR | feed | 学术研究 | arXiv 密码学与安全方向每日新论文，含 LLM 安全前沿 |

## 配置文件
- 信息源：`configs/sources.yaml`
- 筛选规则：`configs/rules.yaml`

关键参数（`configs/rules.yaml`）：
- `relevance.recency_days`：`feed` 最近 N 天过滤（当前 **180 天**）
- `relevance.max_per_source`：每个信息源最多入选条数（当前 **3**），防止 arXiv 等高产源独占日报
- `relevance.min_score`：最低入选分数（当前 **3**）
- `output.summary_max_chars`：摘要截断长度（默认 160）

打分规则简述：
- 命中 `strong_keywords`（如 jailbreak、漏洞、prompt injection）：+4 分/条，无需 AI 上下文
- 命中 `ai_context_keywords`（如 llm、foundation model、模型）：+1 分，且激活弱词加分
- 命中 `weak_keywords`（如 security、adversarial、robustness）：+1 分/条（需 AI 上下文）
- 命中 `deny_keywords`（如 funding、best practices）：直接 -100 分，不入选
- `"eval"` / `"evaluation"` 已从 weak_keywords 移除，改由 `"safety eval"` / `"safety evaluation"`（strong_keywords）覆盖，避免泛 LLM 评测文章误入

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
- `type: “html_list”` 只抓取**配置里写死的页面**，不做全站搜索。
- **当前各源状态**：

  | 源 | 状态 | 备注 |
  |---|---|---|
  | ModelScope Learn | **暂停** | React SPA，静态 HTTP 抓取无效（hrefs_found=0），已确认。待改用 API/RSS 后重新启用 |
  | Volcengine LLMScan | **暂停** | 固定单页 URL，首次推送后被 sent_items 永久去重，无持续信息流价值 |
  | Ant Group AI Safety News | **暂停** | 固定单篇文章 URL（非列表页），原因同上 |

- **已知局限**：
  - ModelScope Learn 为 React SPA，静态 HTTP 抓取可能拿不到文章链接（日志会打印 WARNING 明确标记），此时会回退到单页兜底，效果极差
  - 单页 URL 不变的源（如产品页/固定新闻稿）不适合作为持续信息流接入，应等有 RSS/API 后替换
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


