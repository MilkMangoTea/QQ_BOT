import asyncio
import websockets
import json
import time
from config import *
from function import out, build_params, ran_emoji, ran_emoji_content, rep, url_to_base64, build_params_text_only, ran_rep_text_only, remember_only
from openai import OpenAI

CURRENT_LLM = LLM["ALI-MAX"]
LLM_NAME = CURRENT_LLM["NAME"]
LLM_BASE_URL = CURRENT_LLM["URL"]
LLM_KEY = CURRENT_LLM["KEY"]
client = OpenAI(api_key = LLM_KEY, base_url = LLM_BASE_URL)

template_ask_messages = [{"role": "system", "content": [{"type": "text", "text": PROMPT[2]}]}]
handle_pool = {}
last_update_time = {}

async def handle_message(websocket, event):
    """处理消息事件并发送回复"""
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
        out("当前对话对象:", current_id)

        # 遗忘策略
        if current_id not in handle_pool or time.time() - last_update_time[current_id] > HISTORY_TIMEOUT:
            handle_pool[current_id] = template_ask_messages.copy()
        last_update_time[current_id] = time.time()

        # 提取对话
        for log in message:
            if log["type"] == "text":
                temp_msg += log["data"]["text"]
        handle_pool[current_id].append({"role": "user", "content": [{"type": "text", "text": temp_msg}]})

        # 提取图片
        for log in message:
            if log["type"] == "image":
                image_base64 = url_to_base64(log["data"]["url"])
                handle_pool[current_id].append({"role": "user", "content": [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}}]})
        # 发送请求
        response = client.chat.completions.create(
            model = LLM_NAME,
            messages = handle_pool[current_id]
        )
        # reasoning_content = response.choices[0].message.reasoning_content
        content = response.choices[0].message.content
        handle_pool[current_id].append({"role": "assistant", "content": content})
        out("历史会话:", handle_pool[current_id])

        # 构造并发送API请求
        await websocket.send(json.dumps({
            "action": "send_msg",
            "params": build_params("text", event, content)
        }))

        # 随机发送表情(不够简洁)
        if ran_emoji():
            await websocket.send(json.dumps({
                "action": "send_msg",
                "params": ran_emoji_content(event)
            }))

        print(f"已回复 {msg_type} 消息: {content}")
        print("#######################################")

    except KeyError as e:
        print(f"缺少必要字段: {e}")

async def qq_bot():
    """主连接函数"""
    async with websockets.connect(WEBSOCKET_URI) as ws:
        print("成功连接到WebSocket服务器")
        async for message in ws:
            try:
                event = json.loads(message)
                # 响应"戳一戳"
                if event.get("post_type") == "notice":
                    await ws.send(json.dumps({
                        "action": "send_msg",
                        "params": build_params_text_only(event, ran_rep_text_only())
                    }))
                    continue

                # 过滤非消息事件
                if event.get("post_type") != "message":
                    continue

                # 验证发送者身份
                if rep(event) :
                    await handle_message(ws, event)
                else:
                    remember_only(event, handle_pool, last_update_time, template_ask_messages)


            except json.JSONDecodeError:
                print("收到非JSON格式消息")
            except Exception as e:
                print(f"处理消息时发生错误: {e}")

if __name__ == "__main__":
    while True:
        try:
            asyncio.get_event_loop().run_until_complete(qq_bot())
        except websockets.ConnectionClosed:
            print("连接断开，尝试重连...")
            continue
        except KeyboardInterrupt:
            print("程序已终止")
            break