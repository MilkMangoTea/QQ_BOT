# QQ Bot Framework

一个基于 Python 的 QQ 群聊机器人框架，支持接入多种大语言模型，提供拟人化的对话体验和丰富的功能。

## 特性

- **多模型支持**：集成多种大语言模型
  - DeepSeek (V3, R1)
  - 通义千问 (qwen2.5-vl-72b, qwen-plus)
  - 智谱 GLM-4.5-flash
  - AIZEX (GPT-4.1, GPT-5, Claude-4)
  - 支持模型降级和切换

- **智能交互**
  - 拟人化对话（多种人格模式可选）
  - 群聊随机回复（可配置概率）
  - 被@自动回复
  - AI 智能判断是否回复（基于 LangChain）

- **记忆系统**
  - 短期会话记忆（10分钟超时）
  - 长期记忆（Mem0 + Milvus 向量数据库）
  - 自动记忆管理和检索

- **丰富功能**
  - 图片搜索（支持 Safe/R18 模式）
  - 每日运势推送（定时任务）
  - 表情包随机回复
  - 戳一戳互动
  - 私聊模式支持

- **模块化设计**
  - 清晰的目录结构
  - 易于扩展
  - 配置集中管理

## 快速开始

### 前置要求

- Python 3.8+
- WebSocket服务（推荐使用NapCat）
- 环境变量配置文件

### 部署步骤

1. **克隆仓库到本地**

```bash
git clone [你的仓库地址]
cd QQ_BOT
```

2. **安装依赖**

```bash
pip install -r requirements.txt
```

3. **配置环境变量**

创建环境变量文件 `my_env/api_key.env`（或直接编辑现有文件）：

```env
# 必填配置
DEEPSEEK="your_deepseek_api_key"
ALI="your_qwen_api_key"
ZHIPU="your_glm_api_key"
AIZEX="your_aizex_api_key"

# QQ号配置
MY_QQ_ID=你的QQ号
BOT_QQ_ID=机器人QQ号

# 可选配置（用于图片和记忆功能）
PIXIV_REFRESH_TOKEN="your_pixix_token"
ZILLIZ_API_KEY="your_zilliz_api_key"
```

> 注意：配置文件路径必须在 `/opt/QQ_BOT/my_env/api_key.env` 或创建软链接

4. **配置群聊白名单**

编辑 `src/qqbot/config/config.py`，修改：
- `ALLOWED_GROUPS`：允许机器人响应的群聊列表
- `FORTUNE_GROUPS`：接收每日运势推送的群聊列表
- `WEBSOCKET_URI`：WebSocket连接地址（默认本地3001端口）

5. **启动NapCat**

安装并配置NapCat作为QQ协议端，确保WebSocket服务运行在 `ws://127.0.0.1:3001`

6. **运行机器人**

```bash
python src/qqbot/utils/my_proxy.py
```

### 验证连接

```bash
python tests/test.py
```

测试 API 连接是否正常。

### 配置说明

所有配置项都集中在 `src/qqbot/config/config.py` 文件中：

- **WebSocket配置**
  - `WEBSOCKET_URI`: WebSocket服务器地址
  - `MY_QQ_ID`: 你的QQ号
  - `BOT_QQ_ID`: 机器人QQ号

- **LLM配置**
  - `CURRENT_COMPLETION`: 当前使用的LLM服务
  - 支持的模型：DEEPSEEK-V3/R1、ALI (通义)、ZHIPU、AIZEX等
  - 自动降级机制：主模型失败时尝试备用模型

- **行为配置**
  - `RAN_REP_PROBABILITY`: 随机回复概率 (1-100)
  - `RAN_EMOJI_PROBABILITY`: 表情回复概率
  - `HISTORY_TIMEOUT`: 记忆超时时间（秒）

- **人格配置**
  - `CURRENT_PROMPT`: 选择当前人格模式（0-3）
  - `PROMPT`: 人格提示词数组，包含多种人格设定

- **群组管理**
  - `ALLOWED_GROUPS`: 允许响应的群聊列表
  - `FORTUNE_GROUPS`: 接收每日运势的群聊列表

## 功能特性

### 智能回复系统

- **多种触发模式**
  - 随机概率回复：配置的概率主动参与讨论
  - @回复：被@时自动响应
  - 私聊回复：私聊消息100%响应
  - AI判断：基于上下文智能决定是否回复

- **回复策略**
  - 基于 LangChain 的结构化判断
  - 可配置多个大模型，自动降级切换
  - 记忆系统增强对话连续性

### 命令系统

支持的命令（以 `/s` 为前缀）：

- **图片搜索**
  ```
  /s img <标签...> [r18]
  /s 图片 <标签...> [r18]
  ```
  从多个图片源搜索并返回图片，支持安全模式和R18模式

- **控制台命令**（仅限指定用户私聊使用）
  ```
  /s 群聊 <群号>    # 切换到指定群聊
  /s 私聊 <用户ID>  # 切换到指定私聊
  ```

### 记忆系统

- **短期记忆**：会话上下文管理，10分钟超时自动清理
- **长期记忆**：基于 Mem0 + Milvus 的向量记忆，持久化存储用户信息
- **智能检索**：根据对话内容自动检索相关记忆

### 每日运势

- 自动定时推送每日运势（默认每日9:00）
- 支持多主题（hololive、东方Project等）
- 可配置推送群组列表

## 项目结构

```
QQ_BOT/
├── src/qqbot/           # 源代码目录
│   ├── config/
│   │   └── config.py    # 配置文件
│   ├── core/
│   │   ├── function.py              # 核心功能
│   │   ├── function_cmd.py          # 命令处理
│   │   ├── function_completion.py   # AI判断是否回复
│   │   ├── function_session_memory.py     # 短期记忆
│   │   ├── function_long_turn_memory.py   # 长期记忆
│   │   ├── function_fortune.py      # 运势功能
│   │   └── function_image_providers.py   # 图片源
│   └── utils/
│       └── my_proxy.py    # 主程序入口
├── tests/
│   └── test.py         # 测试文件
├── fortune_resources/   # 运势资源
├── requirements.txt     # 依赖列表
└── README.md

```

## 常见问题

### 环境变量路径问题
如果出现找不到环境变量文件的错误，请确保：
1. 文件位于 `/opt/QQ_BOT/my_env/api_key.env`
2. 或在项目根目录创建 `my_env/api_key.env` 并创建软链接

### 模型切换失败
检查配置中的 `CURRENT_COMPLETION` 和对应模型的 API 密钥是否正确

### 记忆系统报错
确保配置了正确的 ZILLIZ_API_KEY，或关闭长期记忆功能

## 开发说明

### 添加新的人格
在 `config.py` 的 `PROMPT` 数组中添加新的人格描述，并更新 `CURRENT_PROMPT` 索引

### 添加新的LLM
在 `config.py` 的 `LLM` 字典中添加新的模型配置

### 扩展命令
在 `function_cmd.py` 中添加新的命令处理逻辑

## 致谢

特别感谢 @novashen666 的支持与贡献。

## 免责声明

本项目仅供学习和研究使用，请勿用于商业或其他非法用途。

---

