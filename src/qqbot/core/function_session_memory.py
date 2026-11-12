from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import AIMessage, HumanMessage
from src.qqbot.config.config import SELF_USER_ID
from src.qqbot.core.function_message import QQMessageParser, event_message, sender_id, sender_name
from src.qqbot.utils.console import out


@dataclass
# 单个会话的短期记忆容器
class SessionMemory:
    history: BaseChatMessageHistory = field(default_factory=ChatMessageHistory)
    last_update_time: float = field(default_factory=time.time)
    last_proactive_reply_time: float = 0.0  # 上次主动插话的时间
    is_initialized: bool = False
    source_messages: Dict[str, Dict] = field(default_factory=dict)

    def touch(self) -> None:
        self.last_update_time = time.time()

    def mark_proactive_reply(self) -> None:
        """标记一次主动回复"""
        self.last_proactive_reply_time = time.time()

    def is_expired(self, timeout: Optional[float]) -> bool:
        if not timeout or timeout <= 0:
            return False
        return (time.time() - self.last_update_time) > timeout

# 全局的短期记忆管理器
class MemoryManager:
    def __init__(
            self,
            timeout: Optional[float] = None,
            context_window: int = 15  # 提供给 LLM 的最大消息数
    ):
        """
        :param timeout: 会话超时时间（秒）
        :param context_window: 提供给 LLM 的最大消息数
        """
        self._timeout = timeout
        self._context_window = context_window
        self._sessions: Dict[str, SessionMemory] = {}

    # 获取或创建会话
    def get_or_create_session(self, session_id: str) -> SessionMemory:

        session = self._sessions.get(session_id)

        # 会话过期处理：直接清空
        if session is not None and session.is_expired(self._timeout):
            out("⏰ 会话已过期，清空记忆", session_id)
            session = None

        # 创建新会话
        if session is None:
            session = SessionMemory()
            self._sessions[session_id] = session
            out("🆕 创建新会话", session_id)

        session.touch()
        return session

    async def initialize_with_history(
            self,
            session_id: str,
            messages: List[Dict],
            force: bool = False,
            parser=None,
            event_context=None,
    ) -> None:
        session = self.get_or_create_session(session_id)

        # 如果已经初始化且不强制，跳过
        if session.is_initialized and not force:
            return

        # 清空现有历史
        session.history.clear()
        parser = parser or QQMessageParser(
            SELF_USER_ID, quote_chars=500,
            lookup=lambda message_id, seq: self.get_source_message(session_id, message_id, seq))
        for msg in messages[-self._context_window:]:
            self.cache_message(session_id, msg)
        conversation = {}
        if session_id.startswith("group:"):
            conversation = {"message_type": "group", "group_id": session_id.split(":", 1)[1]}
        elif session_id.startswith("user:"):
            conversation = {"message_type": "private", "user_id": session_id.split(":", 1)[1]}
        if event_context:
            for key in ("message_type", "group_id", "user_id"):
                if key in event_context:
                    conversation[key] = event_context[key]

        # 填充历史消息
        for msg in messages[-self._context_window:]:
            try:
                is_self_message = str(sender_id(msg)) == str(SELF_USER_ID)
                content_parts = await parser.parse(
                    event_message(msg), sender_name(msg),
                    origin={**msg, **conversation},
                    include_name=not is_self_message, allow_images=not is_self_message,
                )

                if not content_parts:
                    continue

                # 判断是用户还是机器人
                if is_self_message:
                    # 机器人的消息只保存文本
                    text_only = "".join(p.get("text", "") for p in content_parts if p.get("type") == "text")
                    if text_only:
                        session.history.add_message(AIMessage(content=text_only))
                else:
                    # 用户消息保存多模态内容
                    session.history.add_message(HumanMessage(content=content_parts))

            except Exception as e:
                out("⚠️ 处理历史消息失败", e)
                continue

        session.is_initialized = True
        out("✅ 会话历史已初始化", f"{session_id}，加载 {len(session.history.messages)} 条")

    def cache_message(self, session_id, event):
        """Keep a bounded, per-conversation cache for reply IDs and sequences."""
        if not isinstance(event, dict):
            return
        message_id = event.get("message_id")
        seq = event.get("message_seq", event.get("seq"))
        if message_id is None and seq is None:
            return
        key = f"id:{message_id}" if message_id is not None else f"seq:{seq}"
        source = self.get_or_create_session(session_id).source_messages
        source.pop(key, None)
        source[key] = event
        while len(source) > max(30, self._context_window * 3):
            source.pop(next(iter(source)))

    def get_source_message(self, session_id, message_id=None, seq=None):
        session = self._sessions.get(session_id)
        if session is None or session.is_expired(self._timeout):
            return None
        if seq is not None:
            for event in reversed(list(session.source_messages.values())):
                if str(event.get("message_seq", event.get("seq"))) == str(seq):
                    return event
        return session.source_messages.get(f"id:{message_id}") if message_id is not None else None

    def get_history(self, session_id: str) -> BaseChatMessageHistory:
        """
        获取会话历史记录

        返回会话上下文：
        - 当消息数 <= context_window 时，返回原始 session.history（可修改）
        - 当消息数 > context_window 时，返回裁剪后的新对象（只读，修改不会影响原 session）
        - 调用者应只读取返回的历史，不要直接修改
        - 使用 add_user_message/add_ai_message 方法来添加新消息
        """
        session = self.get_or_create_session(session_id)

        all_messages = session.history.messages

        # 如果消息数不超过限制，直接返回
        if len(all_messages) <= self._context_window:
            return session.history

        # 裁剪：只保留最近的消息（返回新对象，只读）
        limited_history = ChatMessageHistory()
        for msg in all_messages[-self._context_window:]:
            limited_history.add_message(msg)

        return limited_history

    def add_user_message(self, session_id: str, content) -> None:
        """
        添加用户消息（支持多模态）
        content 可以是：
        - str: 纯文本
        - list: 多模态内容 [{"type": "text", "text": "..."}, {"type": "image_url", ...}]
        """
        if not content:
            return
        session = self.get_or_create_session(session_id)

        if isinstance(content, str):
            session.history.add_user_message(content)
        else:
            # 多模态内容
            session.history.add_message(HumanMessage(content=content))

        session.touch()

    def add_ai_message(self, session_id: str, text: str) -> None:
        if not text:
            return
        session = self.get_or_create_session(session_id)
        session.history.add_ai_message(text)
        session.touch()

    def get_recent_dialog_lines(
            self,
            session_id: str,
            take_n: int = 10,
            max_chars_per_line: int = 240,
    ) -> List[str]:
        # 获取最近的对话
        session = self.get_or_create_session(session_id)
        messages = session.history.messages[-take_n:]

        lines: List[str] = []
        for msg in messages:
            role = getattr(msg, "type", "")
            content_raw = getattr(msg, "content", "") or ""

            # 处理多模态内容（list）或纯文本（str）
            if isinstance(content_raw, list):
                text_parts = []
                for part in content_raw:
                    if isinstance(part, dict) and part.get("type") == "text":
                        text_parts.append(part.get("text", ""))
                content = "".join(text_parts).strip()
            else:
                content = content_raw.strip() if isinstance(content_raw, str) else ""

            if not content:
                continue

            if role == "ai":
                line = f"BOT: {content}"
            else:
                line = content

            if max_chars_per_line and len(line) > max_chars_per_line:
                line = line[:max_chars_per_line] + "…"

            lines.append(line)

        return lines

    # 检查会话是否已初始化
    def is_session_initialized(self, session_id: str) -> bool:
        session = self._sessions.get(session_id)
        # 过期会话也需要重新拉取历史；检查时不 touch，避免延长旧会话寿命。
        return (
            session is not None
            and session.is_initialized
            and not session.is_expired(self._timeout)
        )

    # 检查最近是否有主动回复（用于冷却）
    def recent_bot_proactive_reply(self, session_id: str, within_seconds: float = 300) -> bool:
        """
        检查在 within_seconds 秒内是否有过主动回复
        :param session_id: 会话 ID
        :param within_seconds: 时间窗口（秒）
        :return: True 表示冷却中，False 表示可以主动回复
        """
        session = self._sessions.get(session_id)
        if not session:
            return False

        if session.last_proactive_reply_time == 0.0:
            return False

        elapsed = time.time() - session.last_proactive_reply_time
        return elapsed < within_seconds

    # 标记主动回复
    def mark_proactive_reply(self, session_id: str) -> None:
        """标记一次主动回复，用于冷却计时"""
        session = self._sessions.get(session_id)
        if session:
            session.mark_proactive_reply()

    # 手动重置会话
    def reset_session(self, session_id: str) -> SessionMemory:
        session = SessionMemory()
        self._sessions[session_id] = session
        out("🔄 手动重置会话", session_id)
        return session
    # 获取会话统计信息（调试用）
    def get_stats(self, session_id: str) -> dict:
        session = self._sessions.get(session_id)
        if not session:
            return {"exists": False}
        return {
            "exists": True,
            "active_messages": len(session.history.messages),
            "is_initialized": session.is_initialized,
            "is_expired": session.is_expired(self._timeout),
            "age_seconds": time.time() - session.last_update_time
        }

# 计算会话 ID
def calc_session_id(event: dict) -> str:
    msg_type = event.get("message_type")

    if msg_type == "group":
        gid = event.get("group_id")
        return f"group:{gid}"
    elif msg_type == "private":
        uid = event.get("user_id")
        return f"user:{uid}"
    else:
        raise ValueError(f"unknown message_type: {msg_type!r}, event: {event}")
