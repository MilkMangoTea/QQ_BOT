import random
import websockets
import asyncio
import json
import requests
import base64
from config import *
from urllib3.exceptions import InsecureRequestWarning

# 请求构建器
def build_params(type, event, content):
    msg_type = event.get("message_type")
    base = ""
    if type == "text":
        base = {"message": [{"type": "text", "data": {"text": content}}]}
    elif type == "image":
        base = {"message": [{"type": "image", "data": {"file": content, "sub_type": 1, "summary": "[色禽图片]"}}]}
    if msg_type == "private":
        return {**base, "message_type": msg_type, "user_id": event["user_id"]}
    elif msg_type == "group":
        return {**base, "message_type": msg_type, "group_id": event["group_id"]}
    else:
        return 

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

def url_to_base64(url):
    try:
        url = url.replace("https", "http")

        # 添加常见浏览器User-Agent头以避免被拒绝
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 Edg/132.0.0.0'
        }
        
        # 发起请求并设置10秒超时
        requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
        response = requests.get(url, headers=headers, timeout=10, verify=False) 
        response.raise_for_status()  # 检查HTTP错误状态码
        
        # 验证内容类型是否为图片
        content_type = response.headers.get('Content-Type', '')
        if not content_type.startswith('image/'):
            print(f"⚠️ 警告：URL未返回图片内容（Content-Type: {content_type}）")
            return None

        # 编码为Base64字符串
        image_data = response.content
        response.close()
        return base64.b64encode(image_data).decode('utf-8')
        
    except requests.exceptions.RequestException as e:
        print(f"⚠️ 请求失败: {str(e)}")
    except Exception as e:
        print(f"⚠️ 处理异常: {str(e)}")
    return None

# 导入最近十条聊天消息
async def get_nearby_message(websocket, event, llm):
    try:
        group_id = event["group_id"]
        await websocket.send(json.dumps({
            "action": "get_group_msg_history",
            "params": {
                "group_id": group_id,  # 替换成目标群号
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
                    temp_msg = nickname + ": "
                for log2 in message:
                    if log2["type"] == "text":
                        temp_msg += log2["data"]["text"]
                    elif log2["type"] == "image" and llm == LLM["ALI"] and log1.get("user_id") != SELF_USER_ID:
                        image_base64 = url_to_base64(log2["data"]["url"])
                        res.append({"role": "user", "content": [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}}]})
                role = "user" if log1.get("user_id") != SELF_USER_ID else "assistant"
                if temp_msg != nickname + "":
                    res.append({"role": role, "content": [{"type": "text", "text": temp_msg}]})
            return res

    except Exception as e:
            print("⚠️ 获取群聊消息时发生错误:", str(e))


# 控制台
def special_event(event):
    try:
        cmd = event.get("message")[0]["data"]["text"]
        if cmd.startswith(CMD_PREFIX):
            parts = cmd.split(" ", 1)
            if len(parts) == 2 and parts[1] in ALLOWED_GROUPS:
                print(f"💬 正在向群 {parts[1]} 发送消息")
                return {"group_id": parts[1], "message_type": "group"}
            print("⚠️ 格式错误或不合法的群聊")
    except Exception as e:
        print(f"❗ 控制台事件处理失败: {e}")
        return None