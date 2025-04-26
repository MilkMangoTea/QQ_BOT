import random
from config import *
from .function_completion import *
from .function_memory import *

# 随机文字池子
def ran_rep_text_only():
    return random.choice(POKE)

# 戳一戳固定文字响应
def build_params_text_only(event, content):
    base = {"message": [{"type": "text", "data": {"text": content}}]}
    key = "group_id" if "group_id" in event else "user_id"
    msg_type = "group" if key == "group_id" else "private"
    return {**base, "message_type": msg_type, key: event[key]}

# 随机回复
def ran_rep():
    return random.randint(1,100) <= RAN_REP_PROBABILITY

# @回复
def be_atted(event):
    message = event.get("message")
    for log in message:
        if log["type"] == "at" and log["data"]["qq"] == str(SELF_USER_ID):
            return True
    return False

# 条件回复(随机回复，被@，管理员发言，私聊)
def rep(event):
    return ran_rep() or be_atted(event) or event.get("message_type") == "private"

# 表情随机器
def ran_emoji():
    return random.randint(1,100) <= RAN_EMOJI_PROBABILITY

def ran_emoji_content(event):
    return build_params("image", event, random.choice(EMOJI_POOL))

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
        res = []
        if data.get("status") == "ok":
            messages = data.get("data").get("messages")[-MESSAGE_COUNT:]
            for log1 in messages:
                message = log1.get("message")
                nickname = log1.get("sender").get("nickname")
                temp_msg = ""
                if log1.get("user_id") != SELF_USER_ID:
                    temp_msg = nickname + ":"
                for log2 in message:
                    if log2["type"] == "text" and log2["data"]["text"] != "":
                        temp_msg += log2["data"]["text"]
                    elif log2["type"] == "at":
                        target_prompt = ""
                        if int(log2.get("data").get("qq")) == SELF_USER_ID:
                            target_prompt = "(系统提示:对方想和你说话)"
                        else:
                            target_prompt = "(系统提示:对方在和其他人说话)"
                        temp_msg +=  target_prompt
                    elif log2["type"] == "image" and llm == LLM["AIZEX"] and log1.get("user_id") != SELF_USER_ID:
                        image_base64 = url_to_base64(log2["data"]["url"])
                        res.append({"role": "user", "content": [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}}]})
                if temp_msg != nickname + ":" and temp_msg != "":
                    if log1.get("user_id") != SELF_USER_ID:
                        res.append({"role": "user", "content": [{"type": "text", "text": temp_msg}]})
                    else:
                        res.append({"role": "assistant", "content": temp_msg})
            return res

    except Exception as e:
            print("⚠️ 获取群聊消息时发生错误:", str(e))


# 控制台
# /send 群聊/私聊 群号
def special_event(event):
    if event.get("message_type") == "group" or event.get("user_id") != TARGET_USER_ID:
        return False
    try:
        cmd = event.get("message")[0]["data"]["text"]
        if cmd.startswith(CMD_PREFIX):
            parts = cmd.split(" ", 2)

            if len(parts) == 3 and parts[2] in ALLOWED_GROUPS:

                target_type = parts[1]
                target_id = parts[2]

                if target_type == "群聊":
                    print(f"💬 正在向群 {target_id} 发送消息")
                    return {"group_id": target_id, "message_type": "group"}

                elif target_type == "私聊":
                    print(f"💬 正在向用户 {target_id} 发送消息")
                    return {"user_id": target_id, "message_type": "private"}

            print("⚠️ 格式错误或不合法的群聊")
            return None
        else:
            return False

    except Exception as e:
        print(f"❗ 控制台事件处理失败: {e}")
        return None

# 处理 json 格式的回复
def solve_json(response):
    response = re.sub(r"Reasoning[\\s\\S]*?seconds\\s*", "", response).strip()
    lines = response.splitlines()
    if lines[0].startswith("```") and lines[-1].startswith("```"):
        content = "\n".join(lines[1:-1])
    else:
        content = response
    if (content[0] not in ('{', '[')) or (content[-1] not in ('}', ']')):
        return content, None
    data = json.loads(content)
    return data.get("response"), data.get("memory")
