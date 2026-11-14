import json
import random

from src.qqbot.config import config
from src.qqbot.core.function_completion import (
    build_params,
    should_reply_langchain,
)
from src.qqbot.core.function_session_memory import calc_session_id
from src.qqbot.core.function_message import QQMessageParser, event_message, normalize_message
from src.qqbot.utils.console import out
from src.qqbot.utils.image_uploader import get_image_url_or_fallback, to_onebot_image_file

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
    message = normalize_message(event_message(event))
    for log in message:
        if log.get("type") == "at" and str((log.get("data") or {}).get("qq")) == str(config.SELF_USER_ID):
            return True
    return False


# 条件回复(随机回复，被@，管理员发言，私聊)
def is_allowed_group(event):
    return (event.get("message_type") != "group"
            or str(event.get("group_id")) in {str(group_id) for group_id in config.ALLOWED_GROUPS})


def rep(event, memory_manager):
    if not is_allowed_group(event):
        return False

    if (ran_rep() or be_atted(event) or event.get("_reply_to_bot") is True
            or event.get("message_type") == "private"):
        return True

    if not config.ENABLE_NATURAL_LANGUAGE_REPLY:
        return False
    try:
        session_id = calc_session_id(event)
        return should_reply_langchain(event, memory_manager, session_id)
    except Exception as e:
        out("⚠️ NLP 调用异常", e)
        return False


_EMOJI_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def get_available_emojis():
    """返回模型可选择的本地表情文件名。"""
    emojis = []
    if config.EMOJI_ASSET_DIR.is_dir():
        emojis = sorted(
            path.name
            for path in config.EMOJI_ASSET_DIR.iterdir()
            if path.is_file() and path.suffix.lower() in _EMOJI_SUFFIXES
        )
    return emojis


async def build_emoji_params(event, emoji_name):
    """将模型选择的本地表情转换为图片消息参数。"""
    if emoji_name not in get_available_emojis():
        out("⚠️ 忽略不可用的表情", emoji_name)
        return None

    emoji_path = config.EMOJI_ASSET_DIR / emoji_name
    if not emoji_path.is_file():
        out("⚠️ 表情文件不存在", emoji_path)
        return None

    image_file = to_onebot_image_file(await get_image_url_or_fallback(emoji_path.read_bytes()))
    return build_params("image", event, image_file) if image_file else None


# 导入最近聊天消息
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
        out("⚠️ 获取群聊消息失败", e)
        return []

# Keep live and historical message interpretation in one parser.
async def process_single_message(message, nickname, llm, *, parser=None, event=None):
    parser = parser or QQMessageParser(config.SELF_USER_ID)
    content = await parser.parse(message, nickname, origin=event)
    if event is not None:
        event["_reply_to_bot"] = parser.reply_to_bot
    return [{"role": "user", "content": content}] if content else []
