# Deploying the Dormy Telegram bot

阿蓓做的活儿。Phase 2 已经 merge 进 main，下面是把 bot 真正跑起来的步骤。

## 前置：拿到 Telegram bot token

如果 `@dormy_dev01_bot` 是你之前注册过的，token 应该在你某个 1Password / 笔记里。如果搞丢了：

1. Telegram 里跟 [@BotFather](https://t.me/BotFather) 聊
2. 发 `/mybots` → 选 `dormy_dev01_bot` → API Token → "Revoke and regenerate"（如果忘了原来的）
3. 拿到 `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11` 这种格式的 token

---

## 1. 在 Railway 加新 service

```bash
cd /Users/bei/Documents/AI_Dev/dormy_cli/dormy-ai
railway link  # 选 dormy-ai 项目
railway service create dormy-tg  # 或者在 dashboard 手动 New Service
```

或者最简单：去 Railway dashboard → dormy-ai project → **+ New** → **GitHub Repo** → 选 `dormy-ai/dormy-ai` → service 名字填 `dormy-tg`。

## 2. 配置 start command

跟 MCP service 不一样的地方就是 start command。

Dashboard → dormy-tg → Settings → Deploy → **Custom Start Command**：

```
python -m dormy.cli.commands telegram-serve
```

⚠️ 不要让它跟 MCP service 冲突 —— 它们是同一个 repo 的两个 service，根据 start command 区分。

## 3. 设环境变量

dashboard → dormy-tg → Variables → Add：

| 变量 | 值 |
|---|---|
| `DORMY_TELEGRAM_BOT_TOKEN` | 刚才 BotFather 给你的 token |
| `DORMY_DATABASE_URL` | 跟 MCP service 一样（Supabase Session Pooler） |
| `DORMY_OPENROUTER_API_KEY` | Dormy 自己的 OpenRouter key（**不是** BYOK，bot 路径用 Dormy 付费） |
| `DORMY_OPENAI_API_KEY` | 跟 MCP service 一样（embedding 用） |

或者一条命令搞定（在 dormy-tg service 上下文）：

```bash
railway service dormy-tg
railway variables --set "DORMY_TELEGRAM_BOT_TOKEN=<token>" \
                  --set "DORMY_DATABASE_URL=<同 MCP>" \
                  --set "DORMY_OPENROUTER_API_KEY=<dormy 的 key>" \
                  --set "DORMY_OPENAI_API_KEY=<同 MCP>"
```

## 4. Deploy

设完 env vars Railway 会自动 redeploy。看 logs：

```bash
railway logs --service dormy-tg
```

应该看到 `dormy-tg: bot starting (long-polling)`，没有崩。

> Long-polling 不需要公网 endpoint —— bot 主动拉 Telegram 服务器。所以不需要 DNS 也不需要 expose 端口。

## 5. 端到端测试

```bash
# 在本地 dormy-ai 目录
.venv/bin/python -m dormy.cli.commands invite create your-email@example.com
# 输出：https://t.me/dormy_dev01_bot?start=<token>
```

复制那个链接 → 浏览器打开（或者手机 Telegram 直接点） → Telegram 自动 /start <token>。

期待：
1. bot 回 "Welcome to Dormy, your-email@example.com..."
2. 你发一句 "I'm raising a seed round for an AI fundraising tool" → bot 回复
3. 跑 5 轮以上，去 Supabase SQL editor 跑：
   ```sql
   SELECT kind, content, source, created_at
     FROM user_observations
    WHERE source = 'telegram'
    ORDER BY created_at DESC
    LIMIT 10;
   ```
   应该看到从对话里抽出来的 goals / preferences / facts。

## 6. 失效检查

| 症状 | 检查 |
|---|---|
| Bot 不回 | `railway logs --service dormy-tg` —— token 错？数据库连不上？ |
| `/start <token>` 说 invalid | invite_codes 表里 `consumed_at` 已 set；或者 `expires_at` 过期；或者 token 拼错 |
| Bot 回但记忆没存 | `extractor` 默认每 5 轮才 fire；或者 `DORMY_OPENAI_API_KEY` 没设导致 embedding 失败（看 log） |
| Bot 回 "I don't recognize you yet" | `users.telegram_chat_id` 没绑上。重发一个 invite 让用户重新 /start |

## 安全 checklist

- [ ] OpenRouter dashboard 给 Dormy 的 key 设了 monthly hard cap（建议 $50-100）
- [ ] DORMY_TELEGRAM_BOT_TOKEN 只在 Railway env，不在任何 .env 提交到 git
- [ ] 验证 dormy-tg service 跟 MCP service 用了**不同的** start command（否则会冲突）

---

## Followup（不阻 day-1）

- 自动 email approval 通知（lead form 进 Sheet → Apps Script trigger → 调 dormy-ai API → invite 自动发邮件）—— 现在是手动复制链接
- 把用户的 historical observations 注入 bot 的 system prompt（"long-term memory" 真正可见）
- 让 bot 能 call MCP tools（find_investors, draft_intro 等），不仅仅是聊天
