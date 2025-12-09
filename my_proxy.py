import asyncio
import websockets
from core.function import *
from openai import OpenAI

HTTPX_LIMITS = httpx.Limits(max_connections=100, max_keepalive_connections=20, keepalive_expiry=20.0)
HTTPX_TIMEOUT = httpx.Timeout(connect=5.0, read=12.0, write=5.0, pool=5.0)
HTTP_CLIENT = httpx.Client(limits=HTTPX_LIMITS, timeout=HTTPX_TIMEOUT, http2=True)

CURRENT_LLM = config.LLM[config.CURRENT_COMPLETION]
LLM_NAME = CURRENT_LLM["NAME"]
LLM_BASE_URL = CURRENT_LLM["URL"]
LLM_KEY = CURRENT_LLM["KEY"]

client = OpenAI(
    api_key=LLM_KEY,
    base_url=LLM_BASE_URL,
    timeout=15.0,  # 快失败：整体 15 秒超时
    max_retries=0,  # 不做 SDK 重试
    http_client=HTTP_CLIENT,
)

template_ask_messages = [
    {"role": "system", "content": [{"type": "text", "text": config.PROMPT[0] + config.PROMPT[config.CURRENT_PROMPT]}]}]
handle_pool = {}
last_update_time = {}

memory_pool = LocalDictStore()
memory_manager = MemoryManager(timeout=config.HISTORY_TIMEOUT)

# 大模型请求器(注意message不能为空!)
async def ai_completion(message, current_id):
    try:
        user_id = str(current_id)

        # 提取最后一条用户消息文本
        last_user_text = ""
        for m in reversed(message):
            if m.get("role") == "user":
                parts = m.get("content", [])
                last_user_text = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
                last_user_text = re.sub(r"^[^:：]{1,30}\s*[:：]\s*", "", last_user_text).strip()
                break

        # 获取长期记忆
        mem_dic = memory_pool.get(user_id, query=last_user_text)
        mem_prompt = dic_to_prompt_list(mem_dic)
        new_message = message + mem_prompt

        # 转换为 LangChain 消息格式
        lc_messages = convert_openai_to_langchain(new_message)

        # 尝试多个候选模型
        names = [s.strip() for s in str(LLM_NAME).split(",") if s.strip()]
        last_err = None

        for name in names:
            try:
                # 为每个模型创建 LLM 实例
                temp_config = CURRENT_LLM.copy()
                temp_config["NAME"] = name
                llm = create_chat_llm(temp_config)

                # 调用 LangChain LLM
                response = await asyncio.to_thread(llm.invoke, lc_messages)
                content = response.content

                out("🏁 历史会话:", new_message)
                out("原始信息：", content)
                out("✅ 使用模型：", name)

                if not content:
                    content = "嗯"

                # 异步添加长期记忆
                try:
                    asyncio.create_task(
                        asyncio.to_thread(
                            memory_pool.add_turn,
                            user_id=user_id,
                            user_text=last_user_text,
                            assistant_text=content
                        )
                    )
                except Exception as e:
                    print("⚠️ mem0 add_turn 失败：", e)

                return content

            except Exception as e:
                last_err = e
                continue

        print(f"⚠️ 调用 LLM 发生错误(全部候选失败): {last_err}")
        return None

    except Exception as e:
        print(f"⚠️ 调用 LLM 发生错误: {e}")
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
        print(f"⚠️ WebSocket 错误: {e}")
    except Exception as e:
        # 捕获其他类型的异常
        print(f"⚠️ 发送消息时发生错误: {e}")


# 记忆函数
async def remember(websocket, event):
    try:
        # 获取消息类型和内容
        msg_type = event.get("message_type")
        message = event.get("message")
        nickname = event.get("sender").get("nickname")
        current_id = ""
        if msg_type == "group":
            current_id = event["group_id"]
        elif msg_type == "private":
            current_id = event["user_id"]
        current_id = str(current_id)

        # 遗忘策略
        if current_id not in handle_pool or time.time() - last_update_time.get(current_id, 0) > config.HISTORY_TIMEOUT:
            handle_pool[current_id] = template_ask_messages.copy()
            handle_pool[current_id].extend(await get_nearby_message(websocket, event, CURRENT_LLM))
            last_update_time[current_id] = time.time()
            return
        last_update_time[current_id] = time.time()

        msgs = process_single_message(message, nickname, CURRENT_LLM)
        for msg in msgs:
            handle_pool[current_id].append(msg)
            out("💾 新输入:", msg)


    except KeyError as e:
        print(f"⚠️ [remember]缺少必要字段: {e}")


# 处理消息事件并发送回复
async def handle_message(websocket, event):
    try:
        # 获取消息类型和内容
        msg_type = event.get("message_type")
        current_id = ""
        if msg_type == "group":
            current_id = event["group_id"]
        elif msg_type == "private":
            current_id = event["user_id"]
        current_id = str(current_id)

        out("⏳ 当前对话对象:", current_id)

        # 发送请求
        content = await ai_completion(handle_pool[current_id], current_id)

        if content:
            handle_pool[current_id].append({"role": "assistant", "content": [{"type": "text", "text": content}]})

        # 构造并发送API请求
        await send_message(websocket, build_params("text", event, content))

        # 随机发送表情
        if ran_emoji():
            await send_message(websocket, ran_emoji_content(event))

        print(f"✅ 已回复 {msg_type} 消息: {content}")
        print("#######################################")


    except KeyError as e:
        print(f"⚠️ [handle_message]缺少必要字段: {e}")


async def qq_bot():
    """主连接函数"""
    async with websockets.connect(config.WEBSOCKET_URI) as ws:
        print("✅ 成功连接到WebSocket服务器")

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

                    # /s img/图片
                    if isinstance(my_event, dict) and my_event.get("message"):
                        await send_message(ws, my_event)
                        continue

                    # /s 群聊|私聊 <ID>
                    current_id = my_event["group_id"] if my_event["message_type"] == "group" else my_event["user_id"]
                    if current_id not in handle_pool:
                        handle_pool[current_id] = template_ask_messages.copy()
                        handle_pool[current_id].extend(await get_nearby_message(ws, my_event, CURRENT_LLM))
                        last_update_time[current_id] = time.time()
                    content = await ai_completion(handle_pool[current_id], current_id)
                    await send_message(ws, build_params("text", my_event, content))

                else:
                    await remember(ws, event)

                    if rep(event, handle_pool):
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
