"""Normalize OneBot/NapCat messages for both live events and loaded history.

Schemas: https://napcat.apifox.cn/llms.txt
CQ escaping: https://github.com/botuniverse/onebot-11/blob/master/message/string.md
"""

import asyncio
import json
import re
import xml.etree.ElementTree as ET

from src.qqbot.utils.image_uploader import get_image_url_or_fallback
from src.qqbot.utils.console import out


MAX_SEGMENTS = 100
MAX_TEXT = 12000
MAX_DEPTH = 2
_CQ = re.compile(r"\[CQ:([A-Za-z0-9_]+)(?=,|\])")
# Common legacy QQ IDs; unknown/new IDs are retained rather than guessed.
_FACE_NAMES = {
    "0": "惊讶", "1": "撇嘴", "2": "色", "3": "发呆", "4": "得意",
    "5": "流泪", "6": "害羞", "7": "闭嘴", "8": "睡", "9": "大哭",
    "10": "尴尬", "11": "发怒", "12": "调皮", "13": "呲牙", "14": "微笑",
    "15": "难过", "16": "酷", "18": "抓狂", "19": "吐", "20": "偷笑",
    "21": "可爱", "22": "白眼", "23": "傲慢", "24": "饥饿", "25": "困",
    "26": "惊恐", "27": "流汗", "28": "憨笑", "29": "悠闲", "30": "奋斗",
    "31": "咒骂", "32": "疑问", "33": "嘘", "34": "晕", "35": "折磨",
    "36": "衰", "37": "骷髅", "38": "敲打", "39": "再见",
}


def _text(value, limit=1000):
    return str(value)[:limit] if isinstance(value, (str, int, float)) and not isinstance(value, bool) else ""


def _unescape_cq(value, parameter=False):
    if parameter:
        value = value.replace("&#44;", ",")
    return value.replace("&#91;", "[").replace("&#93;", "]").replace("&amp;", "&")


def normalize_message(message):
    """Accept segment arrays, one segment, plain text, or escaped CQ strings."""
    if isinstance(message, str):
        segments, position = [], 0
        for match in _CQ.finditer(message):
            if match.start() < position:
                continue
            if len(segments) >= MAX_SEGMENTS:
                segments.append({"type": "text", "data": {"text": "[消息段过多，已截断]"}})
                return segments
            end = message.find("]", match.end())
            if end < 0:
                break
            if match.start() > position:
                segments.append({"type": "text", "data": {"text": _unescape_cq(message[position:min(match.start(), position + MAX_TEXT + 1)])}})
            data = {}
            # Do not even decode inline forwarding payloads, including huge CQ nodes.
            if match.group(1) not in {"forward", "node"}:
                for item in message[match.end():end][:MAX_TEXT].lstrip(",").split(","):
                    key, separator, value = item.partition("=")
                    if separator:
                        data[key] = _unescape_cq(value, parameter=True)
            segments.append({"type": match.group(1), "data": data})
            position = end + 1
        if position < len(message):
            segments.append({"type": "text", "data": {"text": _unescape_cq(message[position:position + MAX_TEXT + 1])}})
        if len(message) - position > MAX_TEXT:
            segments.append({"type": "text", "data": {"text": "[消息过长，已截断]"}})
        return segments
    if isinstance(message, dict):
        message = [message]
    if not isinstance(message, list):
        return []
    segments = []
    for segment in message[:MAX_SEGMENTS]:
        if isinstance(segment, str):
            segments.append({"type": "text", "data": {"text": segment}})
        elif isinstance(segment, dict) and isinstance(segment.get("type"), str):
            segments.append({"type": segment["type"], "data": segment.get("data") if isinstance(segment.get("data"), dict) else {}})
        else:
            segments.append({"type": "text", "data": {"text": "[无效消息段]"}})
    if len(message) > MAX_SEGMENTS:
        segments.append({"type": "text", "data": {"text": "[消息段过多，已截断]"}})
    return segments


def event_message(event):
    message = event.get("message")
    return message if message is not None else event.get("raw_message", "")


def sender_name(event):
    sender = event.get("sender") if isinstance(event.get("sender"), dict) else {}
    return _text(sender.get("card") or sender.get("nickname") or event.get("nickname") or event.get("name") or "群友", 80)


def sender_id(event):
    sender = event.get("sender") if isinstance(event.get("sender"), dict) else {}
    return event.get("user_id", sender.get("user_id"))


def _card_summary(kind, data):
    raw = data.get("data", data.get("content", ""))
    if not isinstance(raw, str) or len(raw) > MAX_TEXT:
        return f"[{kind.upper()}卡片：内容缺失或过长]"
    found = []

    def add(value):
        value = _text(value, 400).strip()
        if value and value not in found and len(found) < 8:
            found.append(value)

    try:
        if kind == "xml":
            if re.search(r"<!\s*(DOCTYPE|ENTITY)", raw, re.I):
                raise ValueError("XML entities are not supported")
            root = ET.fromstring(raw)
            if root.get("serviceID") == "35" or root.get("action") == "viewMultiMsg":
                return "[合并转发消息，未展开]"
            for element in list(root.iter())[:60]:
                for key in ("title", "brief", "summary", "url", "jumpUrl"):
                    add(element.attrib.get(key))
                if element.tag.rsplit("}", 1)[-1] in {"title", "summary", "desc"}:
                    add(element.text)
        else:
            def visit(value, depth=0):
                if depth > 4:
                    return
                if isinstance(value, dict):
                    for key, item in list(value.items())[:30]:
                        if key in {"title", "desc", "description", "prompt", "content", "url", "jumpUrl", "qqdocurl"}:
                            add(item)
                        if isinstance(item, (dict, list)):
                            visit(item, depth + 1)
                elif isinstance(value, list):
                    for item in value[:10]:
                        visit(item, depth + 1)
            payload = json.loads(raw)
            if isinstance(payload, dict) and payload.get("app") == "com.tencent.multimsg":
                return "[合并转发消息，未展开]"
            visit(payload)
    except (ValueError, ET.ParseError, RecursionError):
        return f"[{kind.upper()}卡片：无法解析]"
    return f"[{kind.upper()}卡片：{'；'.join(found) if found else '无可读摘要'}]"


class QQMessageParser:
    """Use injected echo-based actions; never read the WebSocket directly."""

    def __init__(self, self_user_id, action=None, lookup=None, image_loader=None, quote_chars=1500):
        self.self_user_id = str(self_user_id)
        self.action = action
        self.lookup = lookup
        self.image_loader = image_loader or get_image_url_or_fallback
        self.quote_chars = quote_chars
        self._resolved = {}
        self._lookups_left = 6
        self._deadline = None
        self.reply_to_bot = False

    async def _request(self, action, params):
        if self.action is None or self._lookups_left <= 0:
            return None
        loop = asyncio.get_running_loop()
        if self._deadline is None:
            self._deadline = loop.time() + 10
        timeout = min(3, self._deadline - loop.time())
        if timeout <= 0:
            return None
        self._lookups_left -= 1
        try:
            result = await asyncio.wait_for(self.action(action, params, timeout=timeout), timeout)
            if isinstance(result, dict) and result.get("status") == "ok" and result.get("retcode") == 0:
                return result.get("data")
        except Exception as error:
            out("⚠️ 读取引用或转发消息失败", type(error).__name__)
        return None

    def _same_conversation(self, record, origin):
        if not isinstance(record, dict):
            return False
        if origin.get("message_type") == "group":
            return (record.get("message_type") != "private"
                    and (record.get("group_id") is None
                         or str(record["group_id"]) == str(origin.get("group_id"))))
        return (not record.get("group_id") and record.get("message_type") != "group"
                and (sender_id(record) is None or str(sender_id(record)) in {
                    self.self_user_id, str(origin.get("user_id"))}))

    async def _reply(self, data, origin):
        message_id = data.get("id")
        if (not isinstance(message_id, (str, int)) or isinstance(message_id, bool)
                or not str(message_id) or len(str(message_id)) > 128):
            message_id = None
        seq = _text(data.get("seq"), 40) or None
        key = ("reply", _text(message_id), _text(seq))
        if key in self._resolved:
            return self._resolved[key]
        record = self.lookup(message_id, seq) if self.lookup else None
        if isinstance(record, dict) and seq is not None:
            cached_seq = record.get("message_seq", record.get("seq"))
            if cached_seq is not None and str(cached_seq) != seq:
                record = None
        if record is None and seq is not None and origin.get("group_id") is not None:
            history = await self._request("get_group_msg_history", {
                "group_id": origin["group_id"], "message_seq": str(seq), "count": 2,
                "parse_mult_msg": False,
            })
            records = history.get("messages", []) if isinstance(history, dict) else []
            record = next((item for item in records if isinstance(item, dict)
                           and str(item.get("message_seq", item.get("seq"))) == str(seq)), None)
        if record is None and isinstance(message_id, (str, int)) and not isinstance(message_id, bool):
            record = await self._request("get_msg", {"message_id": message_id})
        if not self._same_conversation(record, origin):
            record = None
        if isinstance(record, dict) and seq is not None:
            actual_seq = record.get("message_seq", record.get("seq"))
            if actual_seq is not None and str(actual_seq) != seq:
                record = None
        self._resolved[key] = record
        return record

    async def parse(self, message, nickname="", origin=None, include_name=True, allow_images=True):
        self.reply_to_bot = False
        self._images_left = 5
        self._chars_left = MAX_TEXT
        self._segments_left = MAX_SEGMENTS
        parts = []
        await self._parts(normalize_message(message), parts, origin or {}, 0, allow_images, set())
        if parts and include_name:
            prefix = f"{_text(nickname or '群友', 80)}:"
            if parts[0]["type"] == "text":
                parts[0]["text"] = prefix + parts[0]["text"]
            else:
                parts.insert(0, {"type": "text", "text": prefix})
        return parts

    def _append(self, parts, text):
        if not text or self._chars_left <= 0:
            return
        text = _text(text, MAX_TEXT + 1)
        if len(text) > self._chars_left:
            text = text[:self._chars_left] + "[内容过长，已截断]"
        self._chars_left = max(0, self._chars_left - len(text))
        if parts and parts[-1]["type"] == "text":
            parts[-1]["text"] += text
        else:
            parts.append({"type": "text", "text": text})

    async def _image(self, data, parts, allow_images):
        summary = _text(data.get("summary") or data.get("name"), 150)
        self._append(parts, f"[图片：{summary}]" if summary else "[图片]")
        source = data.get("url") or data.get("file")
        if not allow_images or self._images_left <= 0:
            return
        if not isinstance(source, str) or not source.startswith(("http://", "https://", "data:image/", "base64://")):
            self._append(parts, "[图片缺少可读取地址]")
            return
        self._images_left -= 1
        try:
            if source.startswith("base64://"):
                source = "data:image/png;base64," + source[len("base64://"):]
            image = source if source.startswith("data:image/") else await asyncio.wait_for(self.image_loader(source), 15)
            if image and image != "base64://error":
                parts.append({"type": "image_url", "image_url": {"url": image}})
            else:
                self._append(parts, "[图片获取失败]")
        except Exception as error:
            out("⚠️ 消息图片解析失败", type(error).__name__)
            self._append(parts, "[图片获取失败]")

    async def _parts(self, segments, parts, origin, depth, allow_images, visiting):
        for segment in segments:
            if self._segments_left <= 0 or self._chars_left <= 0:
                self._append(parts, "[消息内容达到解析上限]")
                break
            self._segments_left -= 1
            kind, data = segment["type"], segment["data"]
            try:
                if kind == "text":
                    self._append(parts, _text(data.get("text"), MAX_TEXT))
                elif kind == "at":
                    target = _text(data.get("qq"))
                    if target == self.self_user_id:
                        text = "(系统提示:对方想和你说话)"
                    elif target == "all":
                        text = "(系统提示:对方在和全体成员说话)"
                    else:
                        text = f"[@{_text(data.get('name'), 80) or '其他群友'}]"
                    self._append(parts, text)
                elif kind == "face":
                    face_id = _text(data.get("id"), 40)
                    name = _FACE_NAMES.get(face_id) or _text(data.get("name"), 60)
                    self._append(parts, f"[QQ表情：{name or '未知表情'}；ID={face_id or '未知'}]")
                elif kind == "mface":
                    self._append(parts, f"[商城表情：{_text(data.get('summary'), 150) or '无文字摘要'}]")
                    if data.get("url"):
                        await self._image(data, parts, allow_images)
                elif kind == "image":
                    await self._image(data, parts, allow_images)
                elif kind == "reply":
                    key = ("reply", _text(data.get("id")), _text(data.get("seq")))
                    if depth >= MAX_DEPTH or key in visiting:
                        self._append(parts, "[引用嵌套已截断]")
                        continue
                    record = await self._reply(data, origin)
                    if record is None:
                        self._append(parts, "[引用消息：原文不可用]")
                        continue
                    if depth == 0 and str(sender_id(record)) == self.self_user_id:
                        self.reply_to_bot = True
                    self._append(parts, f"[引用历史消息开始（{sender_name(record)}）：")
                    chars_left, segments_left = self._chars_left, self._segments_left
                    self._chars_left = min(chars_left, self.quote_chars)
                    self._segments_left = min(segments_left, 20)
                    await self._parts(normalize_message(event_message(record)), parts, origin,
                                      depth + 1, allow_images, visiting | {key})
                    self._chars_left = chars_left - (min(chars_left, self.quote_chars) - self._chars_left)
                    self._segments_left = segments_left - (min(segments_left, 20) - self._segments_left)
                    self._append(parts, "；引用结束]")
                elif kind in {"forward", "node"}:
                    self._append(parts, "[合并转发消息，未展开]")
                elif kind in {"json", "xml"}:
                    self._append(parts, _card_summary(kind, data))
                elif kind == "markdown":
                    self._append(parts, f"[Markdown消息：{_text(data.get('content'), 4000)}]")
                elif kind in {"record", "video", "file", "onlinefile"}:
                    label = {"record": "语音（未转写）", "video": "视频（未解析画面和音轨）",
                             "file": "文件", "onlinefile": "在线文件"}[kind]
                    name = _text(data.get("name") or data.get("file_name"), 150)
                    self._append(parts, f"[{label}{'：' + name if name else ''}]")
                elif kind in {"dice", "rps"}:
                    self._append(parts, f"[{'骰子' if kind == 'dice' else '猜拳'}：结果={_text(data.get('result')) or '未知'}]")
                elif kind in {"share", "music", "contact", "location", "poke", "shake"}:
                    label = {"share": "链接分享", "music": "音乐分享", "contact": "联系人卡片",
                             "location": "位置", "poke": "戳一戳", "shake": "窗口抖动"}[kind]
                    details = "；".join(_text(data.get(key), 400) for key in ("title", "content", "name", "url") if _text(data.get(key)))
                    self._append(parts, f"[{label}{'：' + details if details else ''}]")
                else:
                    self._append(parts, f"[暂不支持的消息段：{_text(kind, 40)}]")
            except Exception as error:
                out("⚠️ 跳过异常消息段", f"{kind}: {type(error).__name__}")
                self._append(parts, f"[消息段解析失败：{_text(kind, 40)}]")

