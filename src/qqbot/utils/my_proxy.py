import asyncio
import websockets
from src.qqbot.core.function import *
from src.qqbot.config.config import *
from src.qqbot.core.function_fortune import setup_daily_fortune_scheduler
from src.qqbot.core.function_long_turn_memory import LocalDictStore
from src.qqbot.core.function_session_memory import calc_session_id

HTTPX_LIMITS = httpx.Limits(max_connections=100, max_keepalive_connections=20, keepalive_expiry=20.0)
HTTPX_TIMEOUT = httpx.Timeout(connect=5.0, read=12.0, write=5.0, pool=5.0)
HTTP_CLIENT = httpx.Client(limits=HTTPX_LIMITS, timeout=HTTPX_TIMEOUT, http2=True)

CURRENT_LLM = config.LLM[config.CURRENT_COMPLETION]
LLM_NAME = CURRENT_LLM["NAME"]
LLM_BASE_URL = CURRENT_LLM["URL"]
LLM_KEY = CURRENT_LLM["KEY"]

template_ask_messages = [
    {"role": "system", "content": [{"type": "text", "text": config.PROMPT[0] + config.PROMPT[config.CURRENT_PROMPT]}]}]
system_prompt = config.PROMPT[0] + config.PROMPT[config.CURRENT_PROMPT]

memory_pool = LocalDictStore()
memory_manager = MemoryManager(
    timeout=config.HISTORY_TIMEOUT,
    context_window=15
)

# 缓存 chain，避免每次都创建新实例
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

        # 解析候选模型列表
        names = [s.strip() for s in str(LLM_NAME).split(",") if s.strip()]

        last_err = None
        for model_name in names:
            try:
                # 为当前模型创建临时配置
                temp_config = CURRENT_LLM.copy()
                temp_config["NAME"] = model_name

                # 使用缓存的 chain
                if model_name not in _CHAIN_CACHE:
                    _CHAIN_CACHE[model_name] = create_chat_chain_with_memory(
                        memory_manager=memory_manager,
                        long_memory_pool=memory_pool,
                        system_prompt=system_prompt,
                        llm_config=temp_config
                    )
                chain = _CHAIN_CACHE[model_name]

                # 调用 chain（支持图片）
                # 将 user_content 转换为 HumanMessage
                from langchain_core.messages import HumanMessage
                input_msg = HumanMessage(content=user_content)
                response = await asyncio.to_thread(
                    chain.invoke,
                    {"input": [input_msg], "long_memory": long_mem},
                    config={"configurable": {"session_id": session_id}}
                )

                # 提取回复内容
                content = response.content if hasattr(response, 'content') else str(response)
                if not content:
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
                memory_manager.initialize_with_history(session_id, history_msgs)

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

                my_event = special_event(event)
                if my_event:
                    continue

                else:
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
