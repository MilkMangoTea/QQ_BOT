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

### Directory Structure
```
src/qqbot/
├── config/
│   └── config.py        # Central configuration with environment variables
├── core/
│   ├── function.py           # Core message processing and AI completion
│   ├── function_cmd.py       # Command system (/s commands)
│   ├── function_completion.py  # LangChain integration for reply decisions
│   ├── function_session_memory.py  # Short-term memory management
│   ├── function_long_turn_memory.py  # Long-term memory (Mem0)
│   ├── function_fortune.py    # Daily fortune telling with image generation
│   └── function_image_providers.py  # Image fetching from multiple sources
└── utils/
    └── my_proxy.py     # Main application entry point
```

### Key Components

**Message Flow**:
1. WebSocket connection receives messages from NapCat
2. `function.py:rep()` decides if bot should reply (random probability, @mentions, private chat, or AI decision)
3. If replying, `ai_completion()` generates response using configured LLM
4. Response is sent back via WebSocket
5. Memory systems update asynchronously

**Configuration** (`config.py`):
- Loads all settings from environment variables at `/opt/QQ_BOT/my_env/api_key.env`
- Manages multiple LLM provider configurations
- Controls bot behavior (reply probabilities, timeouts, personality)
- Stores bot personality prompts and group whitelists

**LLM Integration**:
- Uses LangChain for structured output (reply decisions)
- Fallback chain across multiple models
- Async request handling with httpx

**Memory Systems**:
- Session memory: In-memory store with 10-minute timeout
- Long-term memory: Mem0 with Milvus for persistent storage

### Dependencies
- **Core**: websockets, httpx, asyncio
- **LLM**: openai, langchain, langchain-openai, langchain-community
- **Memory**: mem0ai, pymilvus, faiss-cpu
- **Other**: pillow, apscheduler, Flask

### Before Making Changes
1. Understand the dual memory system - changes to message flow may affect both
2. Check environment variables at `/opt/QQ_BOT/my_env/api_key.env`
3. LLM configurations are arrays - multiple models can be configured for fallback
4. The bot uses WebSocket connection to NapCat, not direct QQ API
5. Fortune telling and image features are optional but integrated

### Testing
- Limited testing setup in `/tests/test.py` for API validation
- No automated test framework configured
- Manual testing requires running NapCat and connecting to QQ