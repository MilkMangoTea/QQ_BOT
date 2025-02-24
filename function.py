import random
import time
import requests
import base64
from config import *
from urllib3.exceptions import InsecureRequestWarning
import json
import websockets

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
    random.seed(time.time())
    ran = random.randint(0,len(POKE)-1)
    return POKE[ran]

# 固定文字响应
def build_params_text_only(event, content):
    base = {"message": [{"type": "text", "data": {"text": content}}]}
    if "group_id" in event:
        return {**base, "message_type": "group", "group_id": event["group_id"]}
    else:
        return {**base, "message_type": "text", "user_id": event["user_id"]}

# 随机回复
def ran_rep():
    random.seed(time.time())
    ran = random.randint(1,100)
    print("回复阈值:", ran)
    if ran <= RAN_REP_PROBABILITY:
        return True
    return False

# @回复
def be_atted(event):
    message = event.get("message")
    for log in message:
        if log["type"] == "at" and log["data"]["qq"] == str(SELF_USER_ID):
            return True
    return False

# 条件回复(随机回复，被@，管理员发言，私聊)
def rep(event):
    if ran_rep() or be_atted(event) or event.get("message_type") == "private":
        return True

# 表情随机器
def ran_emoji():
    random.seed(time.time())
    ran = random.randint(1,100)
    print("表情包阈值:", ran)
    if ran <= RAN_EMOJI_PROBABILITY:
        return True
    return False

def ran_emoji_content(event):
        random.seed(time.time())
        image_id = random.randint(0,len(EMOJI_POOL)-1)
        image_file = EMOJI_POOL[image_id]
        print(image_file)
        return build_params("image", event, image_file)

# 日志输出
def out(tip, content):
    print("----------")
    print(tip)
    print(content)
    print("----------")

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
            print(f"警告：URL未返回图片内容（Content-Type: {content_type}）")
            return None

        # 编码为Base64字符串
        image_data = response.content
        response.close()
        return base64.b64encode(image_data).decode('utf-8')
        
    except requests.exceptions.RequestException as e:
        print(f"请求失败: {str(e)}")
    except Exception as e:
        print(f"处理异常: {str(e)}")
    return None

# 记录但不回复
def remember_only(event, handle_pool, last_update_time, template_ask_messages):
    message = event.get("message")
    if event["user_id"] == SELF_USER_ID:
        return None
    msg_type = event.get("message_type")
    nickname = event.get("sender").get("nickname")
    temp_msg = nickname + ":"
    current_id = ""
    if msg_type == "group":
        current_id = event["group_id"]
    elif msg_type == "private":
        current_id = event["user_id"]

    # 遗忘策略
    if current_id not in handle_pool or time.time() - last_update_time[current_id] > HISTORY_TIMEOUT:
        handle_pool[current_id] = template_ask_messages.copy()
    last_update_time[current_id] = time.time()

    for log in message:
        if log["type"] == "text":
            temp_msg += log["data"]["text"]
    handle_pool[current_id].append({"role": "user", "content": [{"type": "text", "text": temp_msg}]})
    out("新输入:", temp_msg)
    # 提取图片
    for log in message:
        if log["type"] == "image":
            image_base64 = url_to_base64(log["data"]["url"])
            handle_pool[current_id].append({"role": "user", "content": [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}}]})

# 控制台
def special_event(event):
    message = event.get("message")
    cmd = message[0]["data"]["text"]
    if cmd.startswith(CMD_PREFIX):
        parts = cmd.split(" ", 1)
        if len(parts) != 2:
            print("⚠️ 格式错误，应为：/send 群号")
            return
        if parts[1] not in ALLOWED_GROUPS:
            print("不合法的群聊！")
            return

        group_id = parts[1]
        print(f"💬 正在向群 {group_id} 发送消息")

        my_event = {"group_id": group_id, "message_type": "group"}
        return my_event
