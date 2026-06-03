# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Development Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the QQ bot
python src/qqbot/utils/my_proxy.py

# Test API connections (uses test utilities)
python tests/test.py
```

## Project Architecture

This is a QQ chatbot framework designed for natural group chat interactions with the following key architectural components:

### Core Architecture
- **WebSocket-based**: Connects to QQ server via NapCat WebSocket interface
- **Dual Memory System**:
  - Short-term session memory (10-minute conversations)
  - Long-term memory via Mem0 with Milvus vector store
- **Multi-LLM Support**: Fallback system across DeepSeek, Kimi, Qwen, and other providers
- **Modular Design**: Clear separation between configuration, core functions, and utilities
- **Tool System**: LangGraph Agent with tool calling (numpy_calc for complex math)

### Directory Structure
```
src/qqbot/
├── config/
│   └── config.py        # Central configuration with environment variables
├── core/
│   ├── function.py           # Core message processing and reply decision
│   ├── function_cmd.py       # Command system (/s commands)
│   ├── function_completion.py  # AI completion with Agent + tools
│   ├── function_tools.py     # Tool definitions (numpy_calc)
│   ├── function_session_memory.py  # Short-term memory management
│   ├── function_long_turn_memory.py  # Long-term memory (Mem0)
│   ├── function_fortune.py    # Daily fortune telling with image generation
│   └── function_image_providers.py  # Image fetching from multiple sources
└── utils/
    ├── my_proxy.py     # Main application entry point
    └── image_uploader.py  # Image upload and processing
```

### Key Components

#### 1. Natural Language Reply Decision (`function_completion.py:should_reply_langchain`)

**Purpose**: Intelligently decide if the bot should reply to a message

**Logic Flow**:
```python
1. Pure image messages → Return False (don't proactively reply)
   - Exception:被 @ or private chat (handled by function.py:rep())
   
2. Extract text from message
   - If no text → Return False
   
3. LangChain Decision Chain:
   - Input: conversation context (20 messages) + current message
   - Output: Decision object with:
     * should_reply: bool
     * category: FOLLOWUP | QUESTION | CHITCHAT | TOPIC | OTHER | NOISE
     * target: BOT | OTHER_USER | GROUP | UNKNOWN
     * interest: 0~1 (proactive participation score)
     * confidence: 0~1
   
4. Reply Logic:
   - If target=BOT → Reply (passive response)
   - If target=GROUP and category in {TOPIC, CHITCHAT, OTHER}:
     * Check proactive cooldown (5 minutes)
     * If passed → Reply (proactive participation)
   - Confidence filter: < 0.55 and not {QUESTION, FOLLOWUP} → Skip
```

**Key Features**:
- Few-shot examples guide LLM decision-making
- Proactive participation cooldown prevents spam
- Confidence-based filtering reduces false positives

---

#### 2. Image Processing (`my_proxy.py`)

**Purpose**: Convert images to text descriptions for LLM processing

**Why**: LangChain's decision chain and tool system cannot process images directly

**Logic Flow**:
```python
1. Bot decides to reply (via should_reply_langchain or forced conditions)

2. Check for images:
   - Current message has image?
   - Historical messages have image?
   
3. If images found:
   - Generate descriptions using LLM (with caching)
   - Responses API: HumanMessage with image_url
   - Standard API: SystemMessage(prompt) + HumanMessage(image_url)
   
4. Merge descriptions into text:
   - Format: "original_text [图片内容: description1; description2]"
   
5. Create temporary session with described history
   - Original memory unchanged
   - Temporary session contains text descriptions
   
6. Pass to Agent for processing
```

**Design Philosophy**: 
- Unified approach for all API modes (Responses API and standard)
- Maintains code consistency
- Caching prevents redundant API calls

---

#### 3. Reply Generation (`function_completion.py:create_agent_chain_with_memory`)

**Two Modes**:

##### Responses API Mode (FREEGPT)
```python
Features:
  - No tool calling
  - 1 LLM call: Direct persona response
  - Faster and cheaper
  
Flow:
  system_prompt + history + input → LLM → final_answer
```

##### Standard API Mode (DeepSeek, Qwen, etc.)
```python
Features:
  - Tool calling enabled (numpy_calc)
  - 2 LLM calls: Agent + Persona wrapper
  - More accurate for complex tasks
  
Flow:
  1. Agent Chain:
     input → Agent (with tools) → raw_answer (objective)
  
  2. Persona Wrapper:
     raw_answer + system_prompt → LLM → final_answer (with personality)
```

**Tool System**:
- `numpy_calc`: Matrix operations, trigonometry, statistics
- Only called for complex math (simple arithmetic handled directly by LLM)
- LangGraph Agent manages tool invocation

---

### Message Flow

```
1. WebSocket receives message from NapCat
   ↓
2. function.py:rep() - Reply Decision
   - Check: whitelist, random trigger, @mention, private chat
   - If above fails → should_reply_langchain() (NLP decision)
   ↓
3. If should reply → my_proxy.py:ai_completion()
   - Check for images → Generate descriptions if needed
   - Create agent chain (Responses API or Standard)
   ↓
4. Agent Processing
   - Responses API: Direct LLM call
   - Standard: Agent → Tool calls if needed → Persona wrapper
   ↓
5. Send response via WebSocket
   ↓
6. Update memory systems (async)
   - Short-term: session memory
   - Long-term: Mem0 + Milvus
```

---

### Configuration (`config.py`)

**Environment Variables**: `/opt/QQ_BOT/my_env/api_key.env`

**Key Settings**:
- `CURRENT_COMPLETION`: Active LLM model name
- `USE_RESPONSES_API`: Enable Responses API mode
- `RAN_REP_PROBABILITY`: Random reply chance (0-100)
- `ALLOWED_GROUPS`: Whitelist of group IDs
- `SYSTEM_PROMPT`: Bot personality and behavior

**LLM Configurations**:
- Multiple providers: DeepSeek, Kimi, Qwen, FREEGPT (Responses API)
- Fallback chain: Try models in order until success
- Each config: NAME, URL, KEY, USE_RESPONSES_API flag

---

### Dependencies

**Core**:
- `websockets`, `httpx`, `asyncio` - Network and async handling
- `langchain`, `langchain-openai`, `langchain-community` - LLM integration
- `langgraph` - Agent framework for tool calling

**Memory**:
- `mem0ai` - Long-term memory framework
- `pymilvus` - Vector database
- `faiss-cpu` - Vector similarity search

**Other**:
- `numpy` - Tool system calculations
- `pillow` - Image processing
- `apscheduler` - Scheduled tasks
- `Flask` - Web interface (optional)

---

### Recent Changes (2025-01)

1. **Tool System Integration**:
   - Added LangGraph Agent for tool calling
   - `numpy_calc` tool for complex math
   - Responses API mode: No tools (simplified)
   - Standard API mode: Full tool support

2. **Image Processing**:
   - Unified image description generation
   - Both Responses API and standard use text descriptions
   - Caching mechanism to avoid redundant API calls

3. **Code Cleanup**:
   - Removed unused imports (`Runnable`, `RunnableConfig`)
   - Removed invalid `model_kwargs` code
   - Simplified Responses API logic (1 call instead of 2)

4. **Reply Decision**:
   - Pure image messages: No proactive reply (only if @mentioned or private)
   - Proactive participation cooldown (5 minutes)
   - Confidence-based filtering (< 0.55)

---

### Before Making Changes

1. **Memory Systems**: Changes to message flow affect both short-term and long-term memory
2. **Environment Variables**: Check `/opt/QQ_BOT/my_env/api_key.env` for configuration
3. **LLM Fallback**: Multiple models configured - maintain fallback chain
4. **WebSocket Connection**: Uses NapCat, not direct QQ API
5. **Image Processing**: Always generates text descriptions for consistency
6. **Tool System**: Only enabled in Standard API mode, not Responses API

---

### Testing

- API validation: `/tests/test.py`
- Tool calling test: `/tests/test_tool_call.py`
- No automated test framework
- Manual testing requires NapCat + QQ connection

---

### Common Issues

1. **Responses API 404 Errors**: 
   - Known issue with `store` parameter
   - Use Standard API mode for production

2. **Pure Image Messages Not Replied**:
   - By design: Only reply if @mentioned or private chat
   - Bot generates descriptions when it decides to reply

3. **Tool Not Called**:
   - Check if Responses API mode is enabled (no tools)
   - Ensure message requires complex math (simple arithmetic doesn't trigger tools)