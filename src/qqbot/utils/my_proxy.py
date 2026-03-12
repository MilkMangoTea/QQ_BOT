import asyncio
import websockets
import json
import time
from src.qqbot.config import config
from src.qqbot.config.config import FORTUNE_GROUPS
from src.qqbot.core.function import (
    process_single_message,
    get_nearby_message,
    special_event,
    rep,
    build_params_text_only,
    ran_rep_text_only,
    build_params,
    ran_emoji,
    ran_emoji_content,
    get_long_memory_text,
    MemoryManager,
    out
)
from src.qqbot.core.function_completion import create_agent_chain_with_memory
from src.qqbot.core.function_fortune import setup_daily_fortune_scheduler
from src.qqbot.core.function_long_turn_memory import LocalDictStore
from src.qqbot.core.function_session_memory import calc_session_id
from src.qqbot.core.function_tools import TOOLS

CURRENT_LLM = config.LLM[config.CURRENT_COMPLETION]
LLM_NAME = CURRENT_LLM["NAME"]
system_prompt = config.PROMPT[0] + config.PROMPT[config.CURRENT_PROMPT]

memory_pool = LocalDictStore()
memory_manager = MemoryManager(
    timeout=config.HISTORY_TIMEOUT,
    context_window=15
)

# 缓存 chain，避免每次都创建新实例
_CHAIN_CACHE = {}

def _clear_chain_cache():
    """清空 chain 缓存"""
    global _CHAIN_CACHE
    _CHAIN_CACHE = {}

# 大模型请求器(注意message不能为空!)
async def ai_completion(session_id, user_content):
    try:
        user_id = session_id.split(":", 1)[-1] if ":" in session_id else session_id

        # 获取长期记忆
        user_text = "".join([p.get("text", "") for p in user_content if p.get("type") == "text"])
        long_mem = get_long_memory_text(memory_pool, user_id, user_text)

        out("🏁 [ai_completion] 调用 chain, session:", session_id)
        out("📝 [ai_completion] 用户输入:", str(user_content)[:100])

        # 检查当前输入是否有图片
        has_image = any(isinstance(p, dict) and p.get("type") in ["image_url", "image"] for p in user_content)

        # 检查最近历史中是否有图片（最近3条消息）
        if not has_image:
            history = memory_manager.get_history(session_id)
            for msg in history.messages[-3:]:
                if hasattr(msg, 'content') and isinstance(msg.content, list):
                    if any(isinstance(p, dict) and p.get("type") == "image_url" for p in msg.content):
                        has_image = True
                        out("🖼️ 检测到历史消息中有图片", "使用多模态模式")
                        break

        # 解析候选模型列表
        names = [s.strip() for s in str(LLM_NAME).split(",") if s.strip()]

        last_err = None
        for model_name in names:
            try:
                # 为当前模型创建临时配置
                temp_config = CURRENT_LLM.copy()
                temp_config["NAME"] = model_name

                if has_image:
                    # 有图片，直接用 LLM 处理（带人格）
                    from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
                    from src.qqbot.core.function_completion import create_chat_llm

                    llm = create_chat_llm(temp_config)
                    history = memory_manager.get_history(session_id)

                    # 把历史中相邻的图片消息和文字消息合并：
                    # 图片单独一条 + 下一条文字 -> 合并为图片+文字一条
                    raw_msgs = list(history.messages)
                    merged = []
                    i = 0
                    while i < len(raw_msgs):
                        msg = raw_msgs[i]
                        if (
                            isinstance(msg, HumanMessage)
                            and isinstance(msg.content, list)
                            and any(isinstance(p, dict) and p.get("type") == "image_url" for p in msg.content)
                            and not any(isinstance(p, dict) and p.get("type") == "text" for p in msg.content)
                        ):
                            # 纯图片消息，尝试与下一条文字消息合并
                            if (
                                i + 1 < len(raw_msgs)
                                and isinstance(raw_msgs[i + 1], HumanMessage)
                            ):
                                next_msg = raw_msgs[i + 1]
                                next_content = next_msg.content if isinstance(next_msg.content, list) else [{"type": "text", "text": next_msg.content}]
                                merged.append(HumanMessage(content=msg.content + next_content))
                                i += 2
                                continue
                        merged.append(msg)
                        i += 1

                    messages = [SystemMessage(content=system_prompt)]
                    messages.extend(merged)
                    messages.append(HumanMessage(content=user_content))

                    response = await asyncio.to_thread(llm.invoke, messages)
                    content = response.content if hasattr(response, 'content') else str(response)
                else:
                    # 无图片，使用 Agent chain
                    if model_name not in _CHAIN_CACHE:
                        _CHAIN_CACHE[model_name] = create_agent_chain_with_memory(
                            memory_manager=memory_manager,
                            long_memory_pool=memory_pool,
                            system_prompt=system_prompt,
                            llm_config=temp_config,
                            tools=TOOLS
                        )
                    chain = _CHAIN_CACHE[model_name]

                    from langchain_core.messages import HumanMessage
                    input_msg = HumanMessage(content=user_content)
                    response = await asyncio.to_thread(
                        chain.invoke,
                        {"input": [input_msg], "long_memory": long_mem},
                        run_config={"configurable": {"session_id": session_id}}
                    )

                    if isinstance(response, dict):
                        content = response.get("output", "")
                    else:
                        content = response.content if hasattr(response, 'content') else str(response)

                # 过滤掉 Agent 错误信息
                if not content or "Agent stopped due to" in content:
                    content = "嗯"

                out("短期记忆：", memory_manager.get_or_create_session(session_id).history)
                out("原始信息：", content)
                out("✅ 使用模型：", model_name)

                # 把回复加入短期记忆
                memory_manager.add_ai_message(session_id, content)

                # 异步更新长期记忆
                try:
                    asyncio.create_task(
                        asyncio.to_thread(
                            memory_pool.add_turn,
                            user_id=user_id,
                            user_text=user_text,
                            assistant_text=content
                        )
                    )
                except Exception as e:
                    print("⚠️ [ai_completion] mem0 add_turn 失败：", e)

                return content

            except Exception as e:
                last_err = e
                print(f"⚠️ 模型 {model_name} 失败: {e}")
                continue

        # 所有模型都失败
        print(f"⚠️ [ai_completion] 全部候选模型失败: {last_err}")
        return None

    except Exception as e:
        print(f"⚠️ [ai_completion] 调用 LLM 发生错误: {e}")
        return None


# QQ 消息发送器
async def send_message(websocket, params):
    try:
        if params is None:
            raise ValueError("params is None")

        await websocket.send(json.dumps({
            "action": "send_msg",
            "params": params
        }))

    except websockets.exceptions.WebSocketException as e:
        # 捕获 WebSocket 相关异常
        print(f"⚠️ [send_message] WebSocket 错误: {e}")
    except Exception as e:
        # 捕获其他类型的异常
        print(f"⚠️ [send_message] 发送消息时发生错误: {e}")

# 记忆函数
async def remember(websocket, event):
    try:
        session_id = calc_session_id(event)

        # 如果会话未初始化，先拉取历史
        if not memory_manager.is_session_initialized(session_id):
            print(f"🔍 首次记忆，正在拉取历史消息...")
            history_msgs = await get_nearby_message(websocket, event, CURRENT_LLM)
            if history_msgs:
                await memory_manager.initialize_with_history(session_id, history_msgs)

        message = event.get("message")
        nickname = event.get("sender").get("nickname")

        # 处理消息，保留完整的多模态内容
        msgs = await process_single_message(message, nickname, CURRENT_LLM)

        for msg in msgs:
            role = msg.get("role")
            content = msg.get("content", [])

            if role == "user" and content:
                # 直接传递多模态内容
                memory_manager.add_user_message(session_id, content)

                # 提取文本用于日志
                text_parts = []
                for part in content:
                    if isinstance(part, dict):
                        if part.get("type") == "text":
                            text_parts.append(part.get("text", ""))
                        elif part.get("type") == "image_url":
                            text_parts.append("[图片]")

                text = "".join(text_parts).strip()
                if text:
                    out("💾 新用户消息:", text[:80])

    except Exception as e:
        print(f"⚠️ [remember] 异常: {e}")

# 处理消息事件并发送回复
async def handle_message(websocket, event):
    try:
        session_id = calc_session_id(event)

        msg_type = event.get("message_type")
        out("⏳ 当前会话:", session_id)

        # 从 event 提取用户输入（包括文本和图片）
        message = event.get("message")
        nickname = event.get("sender").get("nickname")
        msgs = await process_single_message(message, nickname, CURRENT_LLM)

        # 合并所有用户消息内容（包括图片）
        user_content = []
        for msg in msgs:
            if msg.get("role") == "user":
                user_content.extend(msg.get("content", []))

        if not user_content:
            user_content = [{"type": "text", "text": "[无文本内容]"}]

        # 调用 chain 生成回复
        content = await ai_completion(session_id, user_content)

        if not content:
            return

        # 发送回复
        await send_message(websocket, build_params("text", event, content))

        # 随机发送表情
        if ran_emoji():
            await send_message(websocket, ran_emoji_content(event))

        print(f"✅ 已回复 {msg_type} 消息: {content}")
        print("#######################################")

    except Exception as e:
        print(f"⚠️ [handle_message] 异常: {e}")


async def qq_bot():
    """主连接函数"""
    async with websockets.connect(config.WEBSOCKET_URI) as ws:
        print("✅ 成功连接到WebSocket服务器")

        fortune_scheduler = setup_daily_fortune_scheduler(
            websocket=ws,
            target_groups=FORTUNE_GROUPS,
            push_hour=8,
            push_minute=0,
            theme="random"
        )

        async for message in ws:
            try:
                event = json.loads(message)
                # 响应"戳一戳"
                if event.get("post_type") == "notice" and event.get("sub_type") == "poke" and event.get(
                        "target_id") == config.SELF_USER_ID:
                    await send_message(ws, build_params_text_only(event, ran_rep_text_only()))
                    continue

                # 过滤非消息事件
                if event.get("post_type") != "message":
                    continue

                my_event = await special_event(event)
                if my_event:
                    if my_event.get("message"):
                        await send_message(ws, my_event)
                    continue

                await remember(ws, event)

                if rep(event, memory_manager):
                    await handle_message(ws, event)

            except json.JSONDecodeError:
                print("⚠️ 收到非JSON格式消息")
            except Exception as e:
                print(f"⚠️ 处理消息时发生错误: {e}")


if __name__ == "__main__":
    while True:
        try:
            asyncio.get_event_loop().run_until_complete(qq_bot())

        except (websockets.ConnectionClosed, OSError, ConnectionRefusedError, TimeoutError, websockets.InvalidURI,
                websockets.InvalidHandshake, websockets.WebSocketException):

            print("⏱️ 连接断开，尝试重连...")
            time.sleep(3)
            continue

        except KeyboardInterrupt:
            print("🚫 程序已终止")
            break
