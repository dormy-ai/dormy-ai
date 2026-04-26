# BYOK MCP 端到端测试 Playbook

测试 `mcp.heydormy.ai` BYOK 流程是否真 work。**新开一个 terminal 窗口跑这套，跟当前 dev session 隔离。**

---

## 准备

### 1. 拿一个 fresh OpenRouter key

去 https://openrouter.ai/keys → Create Key → 名字写 "dormy-byok-test" → 复制 key（格式 `sk-or-v1-...`）。

> 注意：用一个新 key，**不要**用你本地 dormy-ai/.env 里那个，这样能验证 BYOK 真的走用户自己的 key（事后看 OpenRouter dashboard 这个 key 有 usage = 验证成功）。

### 2. 确认现有 dormy MCP 没装过

```bash
claude mcp list
```

如果列表里看到 `dormy`，先删掉，避免冲突：

```bash
claude mcp remove dormy
```

---

## Step 1 — Install

```bash
claude mcp add dormy --transport http https://mcp.heydormy.ai/mcp -H "Authorization: Bearer sk-or-v1-你的key"
```

**期待结果:**
```
Added HTTP MCP server dormy with URL https://mcp.heydormy.ai/mcp
```

**验证:**
```bash
claude mcp list
```
应该看到 `dormy` 一行，状态 ✓ Connected。

> 踩坑：如果看到 ✗ Failed to connect，先 `curl -s https://mcp.heydormy.ai/health` 确认 server 还活着；再 `curl -X POST https://mcp.heydormy.ai/mcp -H "Authorization: Bearer sk-or-v1-..." -H "Content-Type: application/json" -H "Accept: application/json,text/event-stream" -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'` 看 raw 响应。

---

## Step 2 — Tools 列出来

新开一个 `claude` session，问：

> 列出来你能调用的所有 dormy 工具

**期待:** Claude 会调用 `tools/list`（或者直接报告）6 个工具：

- `profile_set`
- `scan_product`
- `find_investors`
- `draft_intro`
- `watch_vcs`
- `memory_recall`

如果 Claude 没主动列，自己看 `claude mcp list` 应该能看到工具数量。

---

## Step 3 — 真实跑一个 tool

最容易的 smoke test（不依赖数据库）：

> 用 dormy 帮我找 3 个最近活跃的 Series A consumer VC

**期待:** Claude 调用 `find_investors`，返回 mock 数据（当前 server 端工具大部分还是 mock，Week 3-4 才接真实 backend）。返回 JSON 应该包含 3 个投资人对象（name / firm / focus 等字段）。

> 现在 mock 数据是预期的 —— 重点是验证 **BYOK header → server 接收 → tool 被调用 → 返回 → 显示给用户** 整条链路通了。

---

## Step 4 — 验证 BYOK 真的 work

### 4a. 看 Claude Code log（可选，深度验证）

```bash
tail -f ~/Library/Logs/Claude/mcp-dormy.log
# 或者直接在 ~/Library/Logs/Claude/ 找最新的 mcp-* 日志
```

正常情况：每次 tool 调用都会有 outgoing HTTP POST 到 https://mcp.heydormy.ai/mcp，header 里带 Authorization: Bearer sk-or-v1-...

### 4b. 看 OpenRouter dashboard（最权威）

去 https://openrouter.ai/activity → 看你刚才创建的那个 key

**当前阶段（Week 2 mock 状态）:** 因为 tool 多数返回 mock data，这个 key 的 usage 可能还是 0。这是预期的 —— 真正能产生 usage 的是后续接入 LLM 的 tool（draft_intro 之类的）。

**Week 3-4 后:** 当真实 LLM 调用接入后，这个 key 的 usage 会涨；同时 Dormy 自己的 key（在 Railway 上**没设**）应该完全没动。这是 BYOK 真正生效的最直接信号。

### 4c. 错的 key 应该怎样（negative test）

可选，验证错误处理：

```bash
claude mcp remove dormy
claude mcp add dormy --transport http https://mcp.heydormy.ai/mcp -H "Authorization: Bearer sk-or-v1-INVALID_FAKE_KEY"
```

打开 claude，问 "draft intro to Kirsten Green at Forerunner"。

**期待（当 LLM 调用接入后）:** 应该报 OpenRouter 401 / invalid key 错误。

**当前阶段:** 因为多数 tool 是 mock，可能还是会返回 mock 数据 —— 这是 v1 的局限（soft BYOK），后续 tool 实装后会变成 hard fail。

---

## 失败排查

| 症状 | 检查 |
|---|---|
| `claude mcp list` 显示 ✗ Failed | `curl https://mcp.heydormy.ai/health` 应该 200。如果不 200，Railway service 挂了 |
| 401 / 403 | header 格式错。一定是 `Authorization: Bearer <key>`，注意 Bearer 跟 key 之间一个空格 |
| Connected 但 tools/list 空 | server 进程没 register tools，看 Railway logs：`railway logs`（在 dormy-ai 目录跑） |
| Tool 调用 timeout | streamable-http 需要 SSE，某些代理（公司 VPN）会断。换网络试 |
| `Invalid Host header` 421 | 正常情况不会有 —— 已经把 mcp.heydormy.ai 加到 ALLOWED_HOSTS 了。如果出现说明 server.py 的 TransportSecuritySettings 配置回退了 |

---

## 完成的标志

✅ `claude mcp list` 看到 dormy ✓ Connected  
✅ Claude 能列出 6 个 dormy_* 工具  
✅ 至少 1 个 tool 调用返回结构化数据（哪怕是 mock）  
✅ 没有报 401 / Host / SSL 错误

满足以上四条，BYOK MCP 就算端到端通了。Week 3-4 把真实 backend 接上之后，再回这份 playbook 跑一遍 deep validation。
