# QQ Bot Framework

<div align="center">

🤖 一个基于 Python 的智能 QQ 群聊机器人框架

支持多 LLM 接入 · 双记忆系统 · 拟人化交互 · 模块化设计

</div>

---

## ✨ 特性一览

### 🧠 多 LLM 支持
- **OpenAI 接口集成**：支持 OpenAI 接口调用第三方API
- **防网络波动机制**：主模型失败时自动切换备用模型
- **灵活配置**：支持自定义 API 端点和模型参数

### 💬 智能交互系统
- **多触发模式**
  - 群聊随机回复(可配置概率)
  - @提及自动响应
  - 私聊消息 100% 回复
  - NLP 智能判断
- **拟人化对话**：支持多种人格模式，让对话更自然
- **上下文理解**：结合短期和长期记忆进行连贯对话

### 🧩 双记忆系统
- **短期会话记忆**
  - 基于 session 的临时存储
  - 10 分钟超时自动清理
  - 保持对话连续性
- **长期记忆**
  - Mem0 + Milvus 向量数据库(需自行注册并配置，否则无长期记忆)
  - 持久化存储用户信息(颗粒度至群聊/私聊)
  - 智能检索相关记忆

### 🎯 功能模块
- **图片搜索**：多源图片获取，支持 Safe/R18 模式(由于存在风险，目前已关闭)
- **每日运势**：定时推送，支持多主题(可自行添加)
- **表情互动**：随机表情回复、戳一戳互动
- **命令系统**：灵活的 `/s` 命令前缀系统(由于可信度不可保障，目前已关闭)

### ⚙️ 技术架构
- **异步 WebSocket**：基于 NapCat 的高性能连接
- **模块化设计**：清晰的分层架构，易于扩展
- **配置集中管理**：所有配置项统一管理，便于维护
- **错误处理**：完善的异常处理和降级策略

---

## 🚀 快速开始

### 📋 前置要求

- **Python 3.8+** (推荐 3.10 及以上)
- **NapCat** WebSocket 服务 (或其他兼容的 QQ 协议端)
- **API 密钥**：至少一个 LLM 提供商的 API Key

### 📦 部署步骤

#### 1. 克隆仓库

```bash
git clone [你的仓库地址]
cd QQ_BOT
```

#### 2. 安装依赖

```bash
pip install -r requirements.txt
```

> **依赖说明**：项目使用 `httpx`、`websockets`、`langchain`、`mem0ai` 等核心库

#### 3. 配置环境变量

创建环境变量文件（默认路径：`/opt/QQ_BOT/my_env/api_key.env`，可在 `config.py` 中修改）：

```env
# ========== 必填配置 ==========
# LLM API Keys（至少配置一个）
DEEPSEEK="sk-xxx"              # DeepSeek API Key
ALI="sk-xxx"                   # 阿里云通义千问 API Key
ZHIPU="xxx.xxx"                # 智谱 AI API Key
AIZEX="sk-xxx"                 # AIZEX API Key

# QQ 配置
MY_QQ_ID=123456789             # 你的 QQ 号
BOT_QQ_ID=987654321            # 机器人的 QQ 号

# ========== 可选配置 ==========
# 图片功能（可选）
PIXIV_REFRESH_TOKEN="xxx"      # Pixiv 刷新令牌（用于图片搜索）
EMOJI_ASSET_DIR="fortune_resources/emoji"  # 本地表情目录

# 长期记忆功能（可选）
ZILLIZ_API_KEY="xxx"           # Zilliz Cloud API Key（Milvus 向量数据库）
```

> **提示**：
> - 如果项目不在 `/opt/QQ_BOT` 路径，可以修改 `src/qqbot/config/config.py` 中的环境变量文件路径
> - 或创建软链接：`ln -s /your/path/my_env /opt/QQ_BOT/my_env`

#### 5. 启动 NapCat

确保 NapCat WebSocket 服务正常运行：
- 默认地址：`ws://127.0.0.1:3001`
- 登录你的机器人 QQ 账号
- 确保 WebSocket 服务已开启

#### 5. 运行机器人

```bash
python src/qqbot/utils/my_proxy.py
```

看到以下信息表示启动成功：
```
✅ 长期记忆系统初始化成功
⏰ 每日运势定时任务已启动
🔗 正在连接 WebSocket...
✅ WebSocket 连接成功！
```

### ✅ 验证部署

在 QQ 群聊中：
1. **@机器人**，测试是否响应

## ⚙️ 配置指南

所有配置项都集中在 `src/qqbot/config/config.py` 文件中。

### WebSocket 连接

```python
WEBSOCKET_URI = "ws://127.0.0.1:3001"  # NapCat WebSocket 地址
MY_QQ_ID = 123456789                    # 你的 QQ 号
BOT_QQ_ID = 987654321                   # 机器人 QQ 号
```

### LLM 配置

```python
# 当前使用的模型（可选值：DEEPSEEK, ALI, ZHIPU, AIZEX 等）
CURRENT_COMPLETION = "DEEPSEEK"

# LLM 字典配置（支持自定义模型）
LLM = {
    "DEEPSEEK": {
        "NAME": "deepseek-chat,deepseek-reasoner",  # 支持多模型降级
        "URL": "https://api.deepseek.com",
        "KEY": os.getenv("DEEPSEEK")
    },
    # ... 更多模型配置
}
```

**多模型降级**：在 `NAME` 字段用逗号分隔多个模型名，失败时自动尝试下一个。

### 联网搜索

配置现有的 `DEEPSEEK` 环境变量后，支持工具调用的聊天模型会自动获得 `deepseek_search`。
它通过独立的 DeepSeek Search REST API 查询网页，因此主聊天模型也可以是其他提供商。
这是按次收费的接口，具体计费以 DeepSeek 官方文档为准。

搜索参数统一位于 `src/qqbot/config/config.py` 的 `DEEPSEEK_SEARCH_CONFIG`：

```python
DEEPSEEK_SEARCH_CONFIG = {
    "ENABLED": True,        # 默认启用，也可通过下方环境变量关闭
    "KEY": LLM["DEEPSEEK"]["KEY"],
    "URL": "https://api.deepseek.com/v1/tools/search",
    "TIMEOUT": 15.0,       # 网络请求超时（秒）
    "RESULT_COUNT": 5,     # 返回结果数，接口允许 1 至 50
}
```

在 `my_env/api_key.env` 中设置 `DEEPSEEK_SEARCH_ENABLED=false` 可关闭搜索；修改配置后重启机器人。
没有配置 DeepSeek 密钥时不注册搜索工具，不影响其他聊天模型。
当前 `USE_RESPONSES_API=True` 分支仍沿用原有的无工具模式，不提供联网搜索。

提示词要求模型在用户明确要求搜索、查证，或询问最新新闻、版本、价格、政策等时搜索；
常识、闲聊和主观选择不主动搜索。默认只取摘要，不拉取网页全文；多个检索目标分别核对证据，遗漏时针对缺项补搜，沿用已完成的结果。工具循环受下方执行步数和总限时约束。
查询只发送必要关键词，不发送整段聊天记录或私人信息。搜索内容仅作为外部资料，不能覆盖系统规则。
搜索结果只用于内部核实，默认像群友一样自然作答，不主动提及搜索过程或附来源链接；只有用户明确询问出处时才提供链接。证据不足时用自然语气简短表达不确定。

离线验证（mock HTTP 与 LLM，不消耗 API 额度）：

```bash
python tests/test_deepseek_search.py
```

### 人格生成与后台验收

工具 Agent 从第一轮起就使用当前人格提示词，理解需求和生成答案时保持角色，不再先生成无人格的客观初稿再统一包装。
候选回复生成后，模型在后台检查人格、群聊语境、用户各项要求和真实工具结果。通过则直接发送；不通过时保留原始对话及工具证据，只修正表达或补充遗漏的调用。
Responses API 分支仍无工具，但同样支持人格生成和后台验收，并包含长期记忆背景。

集中配置位于 `src/qqbot/config/config.py` 的 `AGENT_CONFIG`：

```python
AGENT_CONFIG = {
    "REVIEW_ENABLED": True,  # 关闭后直接发送带人格的首轮回复
    "MAX_REVISIONS": 2,     # 最多修正次数，通过即提前结束
    "MAX_GRAPH_STEPS": 32,  # 每次生成的图执行步数，包含模型和工具节点
    "TURN_TIMEOUT": 180.0,  # 机器人一轮生成、工具和验收总限时（秒）
}
```

验收使用当前模型，每次候选回复额外产生一次模型调用，不保证主观风格一定达到预期。
启用验收时，只有明确通过的候选才会发送并写入记忆；达到修正上限仍未通过、验收不可用或修正失败时，本轮不发送草稿、表情或图片。
后台修正保留原始上下文和工具证据，并追加一条继续处理的用户角色消息；避免 DeepSeek 工具思考模式把上一版草稿当作尚未结束的助手回合而报缺少 `reasoning_content`。
验收提示词位于 `src/qqbot/core/function_agent.py` 的 `REVIEW_INSTRUCTION`，按意图、人格、自然度（含去八股）、完成度与事实、格式五项分别返回结论和依据。程序汇总整体判定，任一项不通过就退回修正；缺项、依据为空、状态非法或仍返回旧版 `approved/feedback` 时视为验收不可用，不发送候选。
日志记录验收是否通过、修正次数、各项结论与依据、具体反馈及失败异常；失败项按类别汇总后交给生成模型修正。验收结果是模型判断，不保证人格、风格或事实检查没有误判。
机器人通过异步 `chain.ainvoke` 执行，总限时覆盖记忆检索、图片描述、模型重试、工具和验收。超时会取消后续生成，不发送未验收的兜底文字；已经开始的同步工具请求可能仍会完成。已开始工具执行后发生异常，不自动重做整条链。
同一会话按接收顺序处理，不同群仍可并行。本轮使用独立的上下文快照，图片描述和后台草稿不覆盖群聊历史；首次拉取历史时排除当前消息及其后的消息，避免重复。
发送使用 OneBot echo 回执确认，成功后才写入短期与长期记忆；失败或回执超时不自动重发，避免重复消息。群聊与私聊的长期记忆使用完整会话标识隔离。
渲染附件必须全部准备成功才发送整条回复，避免只发送“图片已生成”的文字。连接断开时取消未完成的消息任务并关闭旧的每日运势调度器，重连后重新创建。
计算工具先检查表达式语法和函数白名单，只开放数学计算，禁止 NumPy 文件读写、模块内部对象和任意 Python 调用；不支持的写法会返回计算错误。
同步脚本可继续使用 `chain.invoke`；处于事件循环中的调用方使用 `await chain.ainvoke`。

离线验证（模拟模型和搜索，不调用外部服务）：

```bash
python tests/test_agent_iteration.py
python tests/test_review_checklist.py
python tests/test_workflow.py
python tests/test_review_delivery.py
python tests/test_numpy_calc.py
```

### QQ 消息段解析

实时事件和首次载入的历史消息使用 `core/function_message.py` 中的同一个解析器，兼容消息段数组、单个消息段、纯文本和 CQ 字符串，按 OneBot 规则解码 CQ 参数转义并保留文本、图片、表情的原始顺序。

- `reply`：优先从当前会话的有界原始消息缓存补出引用。当前消息缓存未命中时，按 ID 调用 `get_msg`，或按 `seq` 查询群历史；明确属于其他会话的结果会被拒绝。引用机器人消息也会触发回复，但引用原文中的 `at` 不会作为当前发言的呼叫。
- 引用正文有明确起止标记，当前引用最多保留 1500 字符，历史引用最多 500 字符、只查本地缓存；最多两层嵌套。当前解析最多进行六次引用查询，单次至多三秒，查询共用十秒预算。失败时保留“原文不可用”及当前正文。
- `face`：常用 QQ 表情转为名称并保留 ID；新表情和未知编号不猜测含义。`mface` 使用商城表情的 `summary`；普通图片和动画表情保留摘要与可用图片地址。
- **合并转发不展开**：`forward`、`node` 及识别出的转发卡片只保留固定占位，不读取节点正文、不调用 `get_forward_msg`；查询群历史时使用 `parse_mult_msg=false`。
- JSON/XML 卡片只提取有界的可读标题、描述和链接，不执行内容或载入外部实体；语音、视频、文件等保留类型标记，尚未做语音转写、视频理解或文件正文读取。未知或损坏的消息段不影响同条消息中的有效文本。
- 一条消息最多处理 100 个消息段、12000 字符和五张图片。收到的图片仅使用网络或图片数据地址，不把 NapCat 的文件名/本机路径当作本进程可读取的路径。发出表情与渲染图片统一将数据 URI 转为 OneBot 的 `base64://` 格式。

接口依据：[NapCat 消息段模型](https://napcat.apifox.cn/246111192d0)、[获取消息](https://napcat.apifox.cn/226656707e0)、[获取群历史](https://napcat.apifox.cn/226657401e0)、[OneBot CQ 字符串规则](https://github.com/botuniverse/onebot-11/blob/master/message/string.md)。

离线消息段验证（不连接 QQ、不调用模型）：

```bash
python tests/test_message_parser.py
python tests/test_workflow.py
```

### 工具链渲染图片

Agent 工具链中的 `render_to_png(content, format)` 支持 `latex`、`markdown`（或 `md`）、`svg`，
生成 PNG 后随文字回复发送普通图片段。仅在模型调用该工具时渲染；`USE_RESPONSES_API=True` 的无工具模式不提供此功能。

图片和幸运签一样暂存于服务器的 `fortune_resources/out/`，使用独立的 `render_*.png` 文件名。
准备好发送所需的 URL 或图片数据后删除临时文件；后续渲染会清理超过一天的残留渲染图片，不删除幸运签和表情包。
上传复用现有 Worker，未配置或上传失败时转换为 OneBot 的 `base64://` 图片段，不要求 NapCat 共享服务器文件目录。

LaTeX 使用 Matplotlib mathtext，支持分数、根号、求和、积分、希腊字母和上下标等数学公式，
暂不支持完整 TeX 文档或 `\\begin{...}` 环境。Markdown 支持标题、列表、引用、链接文字和代码块，
不加载内嵌图片或原始 HTML。SVG 使用 CairoSVG，禁止读取外部资源。
单次渲染限时 20 秒，并限制输入长度和图片尺寸。

安装更新后的 `requirements.txt` 即可获取渲染依赖；Linux 服务器如缺少 Cairo 系统库，需安装 `libcairo2`。
故障排查时，在项目根目录用**运行机器人服务的同一个 Python**执行以下命令，
可直接检查三种格式、渲染子进程和输出目录权限，不调用模型、不上传图片：

```bash
python src/qqbot/utils/content_renderer.py --check
```

日志中的 `render_to_png 开始/成功/失败` 表示真实工具执行情况；失败时服务器日志保留完整异常栈。
离线验证（模拟模型和图片上传，不连接 QQ 或消耗 API 额度）：

```bash
python tests/test_content_renderer.py
```

### 行为配置

```python
# 随机回复概率（1-100），数字越大越活跃
RAN_REP_PROBABILITY = 3

# 表情回复
# 将图片放入 fortune_resources/emoji/；模型会自行决定是否发送以及选择哪一张

# 会话记忆超时时间（秒）
HISTORY_TIMEOUT = 600  # 10 分钟

# 上下文窗口大小（保留最近 N 轮对话）
CONTEXT_WINDOW = 15
```

### 人格配置

```python
# 选择人格（0-3）
CURRENT_PROMPT = 1

# 人格提示词数组
PROMPT = [
    "你是一个友好的助手...",  # 基础人格
    "你是一个活泼可爱的猫娘...",  # 人格 1
    # ... 更多人格
]
```

### 群组管理

```python
# 允许机器人响应的群聊 ID 列表
ALLOWED_GROUPS = []

# 接收每日运势推送的群聊 ID 列表
FORTUNE_GROUPS = []
```

---

## 📖 功能详解

### 💬 智能回复系统

机器人使用多种策略决定是否回复消息：

#### 触发模式
1. **随机概率回复**
   - 按配置的概率（`RAN_REP_PROBABILITY`）主动参与群聊讨论
   - 模拟真实用户的随机性，避免过于活跃

2. **@提及响应**
   - 被@时 100% 回复
   - 支持多人对话场景

3. **私聊模式**
   - 私聊消息 100% 回复
   - 提供完整的上下文支持

4. **AI 智能判断** ⭐
   - 基于 LangChain 的结构化输出
   - 分析对话上下文，判断是否需要回复
   - 避免不必要的打断

#### 工作流程
```
收到消息 → 检查是否在白名单群组 → 判断是否需要回复
           ↓
    是否被@？ → 是 → 100% 回复
           ↓
    随机概率 → 命中 → 调用 LLM 生成回复
           ↓
    AI 判断 → 需要回复 → 调用 LLM 生成回复
```

### 🧠 记忆系统

#### 短期会话记忆
- **存储内容**：最近 15 轮对话（可配置 `CONTEXT_WINDOW`）
- **超时机制**：10 分钟无互动自动清空（`HISTORY_TIMEOUT`）
- **Session ID**：基于群组/用户 ID 和消息 ID 生成
- **实现**：`function_session_memory.py`

**优势**：
- 保持对话连续性
- 理解上下文和代词指代
- 快速响应，无需查询数据库

#### 长期记忆
- **存储内容**：用户信息、偏好、历史交互
- **向量数据库**：Milvus (Zilliz Cloud)
- **记忆框架**：Mem0
- **检索策略**：基于语义相似度的智能检索
- **实现**：`function_long_turn_memory.py`

**优势**：
- 跨会话记忆用户信息
- 个性化回复
- 长期关系建立

**工作流程**：
```
用户消息 → 检索长期记忆 → 结合短期记忆 → 生成回复 → 更新记忆
```

### 🎲 每日运势

- **定时推送**：每天 8:00 自动推送（可在 `function_fortune.py` 中修改）
- **图片生成**：动态生成运势卡片（基于 Pillow）
- **多主题支持**：
  - hololive 角色
  - 东方 Project 角色
  - 自定义主题
- **配置**：在 `FORTUNE_GROUPS` 中添加需要接收运势的群组

**运势内容包括**：
- 幸运数字
- 幸运颜色
- 今日宜/忌
- 运势评分

---

## 🏗️ 技术架构

### 系统架构图

```
┌─────────────────────────────────────────────────────────┐
│                        QQ Bot                           │
├─────────────────────────────────────────────────────────┤
│  WebSocket Client (my_proxy.py)                        │
│    ├─ 接收消息                                         │
│    ├─ 发送消息                                         │
│    └─ 心跳保活                                         │
├─────────────────────────────────────────────────────────┤
│  核心逻辑 (function.py)                                │
│    ├─ rep(): 判断是否回复                             │
│    ├─ ai_completion(): 调用 LLM 生成回复              │
│    └─ send_msg(): 发送消息到 QQ                       │
├─────────────────────────────────────────────────────────┤
│  功能模块                                              │
│    ├─ function_cmd.py: 命令处理                       │
│    ├─ function_completion.py: AI 判断 (LangChain)     │
│    ├─ function_session_memory.py: 短期记忆            │
│    ├─ function_long_turn_memory.py: 长期记忆 (Mem0)   │
│    ├─ function_fortune.py: 每日运势                   │
│    └─ function_image_providers.py: 图片源管理         │
├─────────────────────────────────────────────────────────┤
│  配置层 (config.py)                                    │
│    └─ 环境变量、LLM 配置、行为参数                    │
└─────────────────────────────────────────────────────────┘
          ↓                      ↑
    [NapCat]             [LLM APIs]  [Milvus]
```

### 消息处理流程

```python
# 简化的消息处理流程
async def on_message(data):
    # 1. 解析消息
    message_type = data.get("post_type")
    if message_type != "message":
        return

    # 2. 检查白名单
    group_id = data.get("group_id")
    if group_id not in ALLOWED_GROUPS:
        return

    # 3. 判断是否回复 (rep 函数)
    should_reply = await rep(data)
    if not should_reply:
        return

    # 4. 生成回复
    session_id = calc_session_id(data)
    response = await ai_completion(session_id, user_content)

    # 5. 发送消息
    await send_msg(group_id, response)

    # 6. 更新记忆（异步）
    asyncio.create_task(update_memory(session_id, user_content, response))
```

### LLM 降级策略

```python
# 多模型降级配置
LLM["DEEPSEEK"]["NAME"] = "deepseek-chat,deepseek-reasoner"

# 降级逻辑
for model_name in names:  # ["deepseek-chat", "deepseek-reasoner"]
    try:
        response = await call_llm(model_name, messages)
        return response  # 成功则返回
    except Exception as e:
        last_error = e
        continue  # 失败则尝试下一个模型

# 所有模型失败后返回错误
return "❌ 所有模型都失败了"
```

### 依赖关系

```
核心依赖：
├── websockets (WebSocket 通信)
├── httpx (HTTP 客户端，支持 HTTP/2)
├── asyncio (异步编程)
├── langchain + langchain-openai (AI 判断)
├── mem0ai + pymilvus (长期记忆)
├── pillow (图片处理)
└── apscheduler (定时任务)
```

---

## 📂 项目结构

```
QQ_BOT/
├── src/qqbot/                    # 源代码目录
│   ├── config/
│   │   └── config.py             # 配置管理（环境变量、LLM、行为参数）
│   ├── core/
│   │   ├── function.py           # 核心功能（消息处理、LLM 调用）
│   │   ├── function_cmd.py       # 命令系统（/s 命令解析）
│   │   ├── function_completion.py   # AI 回复判断（LangChain）
│   │   ├── function_session_memory.py   # 短期会话记忆
│   │   ├── function_long_turn_memory.py # 长期记忆（Mem0 + Milvus）
│   │   ├── function_fortune.py   # 每日运势（定时任务、图片生成）
│   │   └── function_image_providers.py  # 图片源管理（Pixiv 等）
│   └── utils/
│       ├── my_proxy.py           # 主程序入口（WebSocket 客户端）
│       └── image_uploader.py     # 图片上传工具
├── tests/
│   └── test.py                   # API 连接测试
├── fortune_resources/            # 运势资源文件
│   ├── characters/               # 角色图片
│   └── fonts/                    # 字体文件
├── my_env/
│   └── api_key.env               # 环境变量（API Keys）
├── requirements.txt              # Python 依赖列表
├── README.md                     # 项目文档（本文件）
└── CLAUDE.md                     # Claude Code 开发指南
```

### 核心文件说明

| 文件 | 功能 | 关键函数/类 |
|-----|------|------------|
| `my_proxy.py` | WebSocket 客户端，主程序入口 | `on_message()`, `main()` |
| `function.py` | 消息处理、LLM 调用 | `rep()`, `ai_completion()`, `send_msg()` |
| `function_cmd.py` | 命令解析和处理 | `handle_command()` |
| `function_completion.py` | AI 判断是否回复 | `should_reply_chain()` |
| `function_session_memory.py` | 短期记忆管理 | `MemoryManager` 类 |
| `function_long_turn_memory.py` | 长期记忆管理 | `LocalDictStore`, `get_long_memory_text()` |
| `function_fortune.py` | 运势功能 | `send_daily_fortune()`, `generate_fortune_image()` |
| `config.py` | 配置管理 | 全局配置变量 |

---

## ❓ 常见问题与故障排查

### 部署相关

#### Q: 找不到环境变量文件
**症状**：启动时提示 `FileNotFoundError: /opt/QQ_BOT/my_env/api_key.env`

**解决方案**：
```bash
# 方案 1：创建软链接
sudo mkdir -p /opt/QQ_BOT
sudo ln -s /your/actual/path/my_env /opt/QQ_BOT/my_env

# 方案 2：修改配置文件路径
# 编辑 src/qqbot/config/config.py，修改环境变量文件路径
```

#### Q: WebSocket 连接失败
**症状**：启动后显示 `❌ WebSocket 连接失败`

**排查步骤**：
1. 检查 NapCat 是否正常运行
2. 确认 WebSocket 端口正确（默认 3001）
3. 检查防火墙设置
4. 查看 NapCat 日志

```bash
# 测试 WebSocket 连接
curl -i -N -H "Connection: Upgrade" \
  -H "Upgrade: websocket" \
  -H "Host: 127.0.0.1:3001" \
  http://127.0.0.1:3001
```

#### Q: 依赖安装失败
**症状**：`pip install` 时出现错误

**解决方案**：
```bash
# 使用国内镜像源
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 或者逐个安装核心依赖
pip install websockets httpx asyncio langchain openai mem0ai pymilvus pillow apscheduler
```

### LLM 相关

#### Q: 模型切换失败或无法调用
**症状**：提示 `❌ 所有模型都失败了`

**排查步骤**：
1. 检查 API Key 是否正确
   ```bash
   # 查看环境变量
   cat /opt/QQ_BOT/my_env/api_key.env | grep DEEPSEEK
   ```

2. 验证 API 连接
   ```bash
   python tests/test.py
   ```

3. 检查模型名称是否正确
   - DeepSeek: `deepseek-chat`, `deepseek-reasoner`
   - 通义千问: `qwen2.5-vl-72b`, `qwen-plus`
   - 智谱: `glm-4-flash`, `glm-4-plus`

4. 查看日志输出，定位具体错误

#### Q: 回复速度很慢
**可能原因**：
- 网络延迟
- 模型响应时间长
- 长期记忆检索耗时

**优化方案**：
```python
# 在 config.py 中调整超时设置
HTTPX_TIMEOUT = httpx.Timeout(
    connect=5.0,    # 连接超时
    read=15.0,      # 读取超时（可适当增加）
    write=5.0,
    pool=5.0
)

# 减少上下文窗口大小
CONTEXT_WINDOW = 10  # 从 15 降低到 10

# 禁用长期记忆（如果不需要）
# 注释掉 function_long_turn_memory.py 中的相关调用
```

### 功能相关

#### Q: 机器人不响应消息
**排查清单**：
- [ ] 检查群组是否在白名单中（`ALLOWED_GROUPS`）
- [ ] 检查回复概率是否太低（`RAN_REP_PROBABILITY`）
- [ ] 尝试@机器人，看是否响应
- [ ] 查看控制台日志，是否有错误输出
- [ ] 检查 NapCat 是否收到消息

#### Q: 每日运势没有推送
**排查步骤**：
1. 检查群组是否在 `FORTUNE_GROUPS` 列表中
2. 确认定时任务是否启动（查看启动日志）
3. 检查时区设置是否正确
4. 查看 `fortune_resources/` 目录是否存在必要资源

```python
# 在 function_fortune.py 中手动触发测试
from src.qqbot.core.function_fortune import send_daily_fortune
asyncio.run(send_daily_fortune())
```

### 记忆系统

#### Q: 长期记忆功能报错
**症状**：提示 Milvus 或 Mem0 相关错误

**解决方案**：
```python
# 方案 1：配置 Zilliz Cloud API Key
# 在 api_key.env 中添加：
ZILLIZ_API_KEY="your_zilliz_api_key"

# 方案 2：禁用长期记忆
# 在 function_long_turn_memory.py 中注释掉 Mem0 初始化
# 或在 my_proxy.py 中跳过长期记忆相关调用
```

#### Q: 短期记忆清空太快/太慢
**调整方法**：
```python
# 在 config.py 中修改超时时间
HISTORY_TIMEOUT = 1200  # 改为 20 分钟（默认 600 秒）
```

---

## 🛠️ 开发指南

### 添加新的人格

1. 编辑 `src/qqbot/config/config.py`
2. 在 `PROMPT` 数组中添加新的人格描述

```python
PROMPT = [
    "基础设定...",  # 索引 0（必须保留）
    "活泼的猫娘设定...",  # 索引 1
    "成熟的姐姐设定...",  # 索引 2
    "你的新人格设定：是一个博学的学者，说话严谨认真，经常引用古籍...",  # 索引 3（新增）
]

# 切换到新人格
CURRENT_PROMPT = 3
```

### 添加新的 LLM 提供商

1. 在环境变量文件中添加 API Key
```env
MY_NEW_LLM_KEY="sk-xxxxx"
```

2. 在 `config.py` 中添加 LLM 配置
```python
LLM = {
    # ... 现有配置
    "MY_NEW_LLM": {
        "NAME": "my-model-name",  # 或 "model-1,model-2" 支持降级
        "URL": "https://api.example.com",  # API 端点
        "KEY": os.getenv("MY_NEW_LLM_KEY")
    }
}

# 设置为当前使用的模型
CURRENT_COMPLETION = "MY_NEW_LLM"
```

3. 如果 API 格式不兼容 OpenAI，需要修改 `function.py` 中的 `ai_completion()` 函数

### 自定义消息回复逻辑

在 `src/qqbot/core/function.py` 中修改 `rep()` 函数：

```python
async def rep(data):
    """判断是否回复"""
    # ... 现有逻辑

    # 添加自定义规则
    message_text = data.get("raw_message", "")

    # 规则 1：检测关键词
    keywords = ["帮助", "help", "使用说明"]
    if any(kw in message_text for kw in keywords):
        await send_msg(group_id, "命令列表：\n/s img - 图片搜索\n...")
        return False  # 已处理，不再调用 LLM

    # 规则 2：特殊时段
    current_hour = datetime.now().hour
    if 2 <= current_hour < 6:  # 凌晨 2-6 点降低活跃度
        if random.randint(1, 100) > 1:  # 只有 1% 概率回复
            return False

    # ... 继续原有逻辑
```

### 添加定时任务

在 `src/qqbot/core/function_fortune.py` 中添加新的定时任务：

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

def setup_custom_scheduler(websocket):
    """设置自定义定时任务"""
    scheduler = AsyncIOScheduler()

    # 任务 1：每小时整点提醒
    async def hourly_reminder():
        hour = datetime.now().hour
        message = f"现在是 {hour} 点整"
        for group_id in config.ALLOWED_GROUPS:
            await send_msg_via_websocket(websocket, group_id, message)

    scheduler.add_job(
        hourly_reminder,
        CronTrigger(hour="*", minute=0),  # 每小时 0 分触发
        id="hourly_reminder"
    )

    # 任务 2：每周一早上 9 点发送周报
    async def weekly_summary():
        message = "新的一周开始了！"
        for group_id in config.FORTUNE_GROUPS:
            await send_msg_via_websocket(websocket, group_id, message)

    scheduler.add_job(
        weekly_summary,
        CronTrigger(day_of_week="mon", hour=9, minute=0),
        id="weekly_summary"
    )

    scheduler.start()
    print("✅ 自定义定时任务已启动")
```

### 调试技巧

#### 启用详细日志
```python
# 在 my_proxy.py 开头添加
import logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
```

#### 测试单个功能
```python
# 测试 AI 完成功能
from src.qqbot.core.function import ai_completion
import asyncio

async def test():
    session_id = "test:12345"
    user_content = [{"type": "text", "text": "你好"}]
    response = await ai_completion(session_id, user_content)
    print(response)

asyncio.run(test())
```

#### 模拟消息
```python
# 模拟群聊消息进行测试
test_message = {
    "post_type": "message",
    "message_type": "group",
    "group_id": 123456789,
    "user_id": 987654321,
    "message_id": 12345,
    "raw_message": "测试消息",
    "message": [{"type": "text", "data": {"text": "测试消息"}}]
}

await on_message(test_message)
```

---

---

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

### 提交代码
1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

### 代码规范
- 使用 Python PEP 8 风格
- 添加必要的注释和文档字符串
- 测试新功能

---

## 📄 许可证

本项目仅供学习和研究使用。

## 🙏 致谢

- 特别感谢 **@novashen666** 的支持与贡献
- 感谢 NapCat 项目提供的 QQ 协议实现

---

## ⚠️ 免责声明

- 本项目仅供学习和研究使用
- 请遵守相关法律法规和服务条款
- 请勿用于商业或其他非法用途
- 使用本项目所产生的一切后果由使用者自行承担

---

<div align="center">

**Made with ❤️ by QQ Bot Framework Contributors**

如有问题或建议，欢迎提交 [Issue](https://github.com/your-repo/issues)

</div>
