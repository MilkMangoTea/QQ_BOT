from src.qqbot.core.function_completion import *
from src.qqbot.core.function_cmd import *
from src.qqbot.core.function_session_memory import *
import json

# 随机文字池子
def ran_rep_text_only():
    return random.choice(config.POKE)


# 固定文字响应
def build_params_text_only(event, content):
    base = {"message": [{"type": "text", "data": {"text": content}}]}
    key = "group_id" if "group_id" in event else "user_id"
    msg_type = "group" if key == "group_id" else "private"
    return {**base, "message_type": msg_type, key: event[key]}


# 随机回复
def ran_rep():
    return random.randint(1, 100) <= config.RAN_REP_PROBABILITY


# @回复
def be_atted(event):
    message = event.get("message")
    for log in message:
        if log["type"] == "at" and log["data"]["qq"] == str(config.SELF_USER_ID):
            return True
    return False


# 条件回复(随机回复，被@，管理员发言，私聊)
def rep(event, memory_manager):
    if event.get("message_type") == "group" and event.get("group_id") not in config.ALLOWED_GROUPS:
        return False

    if ran_rep() or be_atted(event) or event.get("message_type") == "private":
        return True

    try:
        session_id = calc_session_id(event)
        return should_reply_langchain(event, memory_manager, session_id)
    except Exception as e:
        print(f"⚠️ [rep] NLP 调用异常: {e}")
        return False


# 表情随机器
def ran_emoji():
    return random.randint(1, 100) <= config.RAN_EMOJI_PROBABILITY


def ran_emoji_content(event):
    return build_params("image", event, random.choice(config.EMOJI_POOL))


# 日志输出
def out(tip, content):
    print(f"----------\n{tip}\n{content}\n----------")


# 导入最近十条聊天消息
async def get_nearby_message(websocket, event, llm):
    try:
        msg_type = event.get("message_type")
        key = "group_id" if msg_type == "group" else "user_id"
        act = "get_group_msg_history" if msg_type == "group" else "get_friend_msg_history"
        current_id = event[key]
        await websocket.send(json.dumps({
            "action": act,
            "params": {
                key: current_id,
                "message_seq": 0  # 为0时从最新消息开始抓取
            }
        }))
        response = await websocket.recv()
        data = json.loads(response)

        if data.get("status") == "ok":
            messages = data.get("data", {}).get("messages", [])
            return messages[-config.MESSAGE_COUNT:] if messages else []
        return []

    except Exception as e:
        print("⚠️ 获取群聊消息时发生错误:", str(e))
        return []

# 处理一条 CQ 消息，生成可直接塞进 handle_pool 的列表
async def process_single_message(message, nickname, llm):
    results = []
    if not message or not isinstance(message, list):
        out("⚠️ message 无效或为空", 400)
        return []

    # 拼文本
    name = nickname or ""
    at_prompt = ""   # 专门存放 @ 生成的提示（昵称和冒号之间）
    text_body = ""   # 普通文字都拼到这里

    for log in message:
        log_type = log.get("type")
        data = log.get("data", {})
        # 文本
        if log_type == "text":
            txt = data.get("text") or ""
            if txt:
                text_body += txt
        # @
        elif log_type == "at":
            qq = int(data.get("qq", 0))

            if qq == config.SELF_USER_ID:
                target_prompt = "(系统提示:对方想和你说话)"
            else:
                target_prompt = "(系统提示:对方在和其他人说话)"
            # 放到昵称和冒号之间
            at_prompt += target_prompt
        # 图片
        elif log_type == "image":
            image_base64 = await url_to_base64(data.get("url"))
            if image_base64:
                results.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": image_base64}
                        }
                    ]
                })
            else:
                results.append({
                    "role": "user",
                    "content": [{
                        "type": "text",
                        "text": "(系统提示: 图片获取失败)"
                    }]
                })

    if text_body or at_prompt:
        # 昵称 + at 提示 + 冒号 + 文本
        temp_msg = f"{name}{at_prompt}:{text_body}"
        if temp_msg != name + ":":
            results.append({
                "role": "user",
                "content": [{
                    "type": "text",
                    "text": temp_msg
                }]
            })

    return results
