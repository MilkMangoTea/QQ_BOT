import asyncio
import httpx
import websockets
import time
from core.function import *
from openai import OpenAI
import os

# 创建状态文件路径
STATUS_FILE = os.path.join(os.path.dirname(__file__), "data", "bot_status.json")
os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)

HTTPX_LIMITS  = httpx.Limits(max_connections=100, max_keepalive_connections=20, keepalive_expiry=20.0)
HTTPX_TIMEOUT = httpx.Timeout(connect=5.0, read=12.0, write=5.0, pool=5.0)
HTTP_CLIENT   = httpx.Client(limits=HTTPX_LIMITS, timeout=HTTPX_TIMEOUT, http2=True)

CURRENT_LLM  = config.LLM[config.CURRENT_COMPLETION]
LLM_NAME     = CURRENT_LLM["NAME"]
LLM_BASE_URL = CURRENT_LLM["URL"]
LLM_KEY      = CURRENT_LLM["KEY"]

client = OpenAI(
    api_key=LLM_KEY,
    base_url=LLM_BASE_URL,
    timeout=15.0,     # 快失败：整体 15 秒超时
    max_retries=0,    # 不做 SDK 重试
    http_client=HTTP_CLIENT,
)

template_ask_messages = [{"role": "system", "content": [{"type": "text", "text": config.PROMPT[0] + config.PROMPT[config.CURRENT_PROMPT]}]}]
handle_pool = {}
last_update_time = {}


# 更新状态文件，供Web界面读取
def update_status(status="online", connections=None):
    if connections is None:
        connections = {}

    status_data = {
        "status": status,
        "connections": connections,
        "last_activity": time.time(),
        "memory_count": len(LocalDictStore().list_ids())
    }

    try:
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(status_data, f, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️ 更新状态文件失败: {e}")

# 大模型请求器(注意message不能为空，deepseek的assistant里面不能有text!)
def ai_completion(message, current_id):
    try:

        memory_pool = LocalDictStore()
        new_message = message + dic_to_prompt_list(memory_pool.get(str(current_id)))

        # 将 LLM_NAME 视为逗号分隔的候选模型序列：先依次试这些模型，再兜底 DeepSeek
        names = [s.strip() for s in str(LLM_NAME).split(",") if s.strip()]
        cands = [(name, LLM_BASE_URL, LLM_KEY) for name in names]

        # 兜底：DeepSeek-V3（若当前就已是 DeepSeek 则不会多加）
        dsv3 = config.LLM["DEEPSEEK-V3"]
        if not (LLM_BASE_URL == dsv3["URL"] and LLM_KEY == dsv3["KEY"] and any(n == dsv3["NAME"] for n in names)):
            cands.append((dsv3["NAME"], dsv3["URL"], dsv3["KEY"]))

        last_err = None
        for name, url, key in cands:
            try:
                # 复用默认 client（相同 base_url/key），否则临时建一个
                cli = client if (url == LLM_BASE_URL and key == LLM_KEY) else OpenAI(
                    api_key=key, base_url=url, timeout=40.0, max_retries=2, http_client=HTTP_CLIENT
                )
                resp = cli.chat.completions.create(model=name, messages=new_message)
                out("原始信息：", resp.choices[0].message.content)
                print(f"✅ 使用模型: {name}")
                content, memory_dict = solve_json(resp.choices[0].message.content)
                memory(memory_dict, current_id, memory_pool)

                # 更新状态
                update_status(connections=handle_pool)

                return content

            except Exception as e:
                last_err = e
                continue

        print(f"⚠️ 调用 OpenAI API 发生错误(全部候选失败): {last_err}")
        update_status(connections=handle_pool)
        return None

    except Exception as e:
        # 捕获异常并打印错误信息
        print(f"⚠️ 调用 OpenAI API 发生错误: {e}")

        return None

# QQ 消息发送器
async def send_message(websocket, params):
    try:
        await websocket.send(json.dumps({
            "action": "send_msg",
            "params": params
        }))
        # 更新状态
        update_status(connections=handle_pool)

    except websockets.exceptions.WebSocketException as e:
        # 捕获 WebSocket 相关异常
        print(f"⚠️ WebSocket 错误: {e}")
    except Exception as e:
        # 捕获其他类型的异常
        print(f"⚠️ 发送消息时发生错误: {e}")

# 记忆函数
async def remember(websocket ,event):
    try:
        # 获取消息类型和内容
        msg_type = event.get("message_type")
        message = event.get("message")
        nickname = event.get("sender").get("nickname")
        temp_msg = nickname + ":"
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

        # 提取对话
        for log in message:
            if log["type"] == "text":
                temp_msg += log["data"]["text"]
            elif log["type"] == "at":
                if int(log.get("data").get("qq")) == config.SELF_USER_ID:
                    target_prompt = "(系统提示:对方想和你说话)"
                else:
                    target_prompt = "(系统提示:对方在和其他人说话)"
                temp_msg +=  target_prompt
            elif log["type"] == "image":
                if CURRENT_LLM != config.LLM["AIZEX"]:
                    out("🛑 识图功能已关闭",404)
                    continue
                image_base64 = url_to_base64(log["data"]["url"])
                if image_base64:
                    handle_pool[current_id].append({"role": "user", "content": [{"type": "image_url", "image_url": {"url": image_base64}}]})
                    out("✅ 新输入:", "[图片]")
                else:
                    handle_pool[current_id].append({"role": "user", "content": [{"type": "text", "text": "(系统提示: 图片获取失败)"}]})

        if temp_msg != nickname + ":":
            handle_pool[current_id].append({"role": "user", "content": [{"type": "text", "text": temp_msg}]})
            out("✅ 新输入:", temp_msg)

        # 更新状态
        update_status(connections=handle_pool)

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
        content = ai_completion(handle_pool[current_id], current_id)

        if content:
            handle_pool[current_id].append({"role": "assistant", "content": content})
        out("🏁 历史会话:", handle_pool[current_id])

        # 构造并发送API请求
        await send_message(websocket, build_params("text", event, content))

        # 随机发送表情
        if ran_emoji():
            await send_message(websocket, ran_emoji_content(event))

        print(f"✅ 已回复 {msg_type} 消息: {content}")
        print("#######################################")

        # 更新状态
        update_status(connections=handle_pool)

    except KeyError as e:
        print(f"⚠️ [handle_message]缺少必要字段: {e}")

async def qq_bot():
    """主连接函数"""
    async with websockets.connect(config.WEBSOCKET_URI) as ws:
        print("✅ 成功连接到WebSocket服务器")

        # 连接成功后更新状态
        update_status("online")

        # 注册信号处理函数
        signal.signal(signal.SIGUSR1, reload_config)
        print("已注册配置重载信号处理函数")

        async for message in ws:
            try:
                event = json.loads(message)
                # 响应"戳一戳"
                if event.get("post_type") == "notice" and event.get("sub_type") == "poke" and event.get("target_id") == config.SELF_USER_ID:
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
                    content = ai_completion(handle_pool[current_id], current_id)
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
            # 启动时更新状态
            update_status("starting")

            asyncio.get_event_loop().run_until_complete(qq_bot())


        except (websockets.ConnectionClosed, OSError, ConnectionRefusedError, TimeoutError, websockets.InvalidURI,websockets.InvalidHandshake, websockets.WebSocketException):

            # 更新断开连接状态
            update_status("disconnected")

            print("⏱️ 连接断开，尝试重连...")
            time.sleep(3)
            continue

        except KeyboardInterrupt:

            # 更新终止状态
            update_status("offline")
            print("🚫 程序已终止")
            break