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
