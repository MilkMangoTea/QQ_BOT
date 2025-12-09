from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.chat_history import BaseChatMessageHistory

__all__ = [
    "SessionMemory",
    "MemoryManager",
    "calc_session_id",
]


@dataclass
class SessionMemory:
    """
    单个会话的短期记忆容器，封装 LangChain 的 ChatMessageHistory，
    并记录最近一次更新的时间戳，方便做超时清理 / 过期重置。
    """
    history: BaseChatMessageHistory = field(default_factory=ChatMessageHistory)
    last_update_time: float = field(default_factory=time.time)

    def touch(self) -> None:
        self.last_update_time = time.time()

    def is_expired(self, timeout: Optional[float]) -> bool:
        """
        根据 timeout 判断是否过期。
        timeout 为 None 或 <=0 时，认为永不过期。
        """
        if not timeout or timeout <= 0:
            return False
        return (time.time() - self.last_update_time) > timeout


class MemoryManager:
    """
    全局的短期记忆管理器
    - 通过 session_id 区分会话
    - 内部为每个会话维护一个 SessionMemory（底层是 ChatMessageHistory）
    - 提供：
        * get_or_create_session          拿到某个会话的 SessionMemory
        * get_history                    拿到 BaseChatMessageHistory（给 RunnableWithMessageHistory 用）
        * add_user_message / add_ai_message  追加用户 / 机器人消息
        * get_recent_dialog_lines        取最近 N 条对话，格式化成字符串列表（给判定链用）
        * reset_session / drop_session   手动重置 / 删除某个会话
    """

    def __init__(self, timeout: Optional[float] = None):
        """
        :param timeout: 会话超时时间（秒）；超过则认为过期，下次访问时会重建 SessionMemory。
        """
        self._timeout = timeout
        self._sessions: Dict[str, SessionMemory] = {}

    # 会话基础操作

    # 获取某个 session 的 SessionMemory；不存在或已过期则重建。
    def get_or_create_session(self, session_id: str) -> SessionMemory:
        session = self._sessions.get(session_id)

        if session is None or session.is_expired(self._timeout):
            session = SessionMemory()
            self._sessions[session_id] = session

        session.touch()
        return session

    # 直接拿指定 session 的 ChatMessageHistory。
    def get_history(self, session_id: str) -> BaseChatMessageHistory:
        return self.get_or_create_session(session_id).history

    # 强制重置某个 session 的记忆。返回新的 SessionMemory。
    def reset_session(self, session_id: str) -> SessionMemory:
        session = SessionMemory()
        self._sessions[session_id] = session
        return session

    # 丢弃某个 session 的记忆
    def drop_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    # 追加消息
    # 往指定会话追加一条用户消息。
    def add_user_message(self, session_id: str, text: str) -> None:
        if not text:
            return
        session = self.get_or_create_session(session_id)
        session.history.add_user_message(text)
        session.touch()

    def add_ai_message(self, session_id: str, text: str) -> None:
        if not text:
            return
        session = self.get_or_create_session(session_id)
        session.history.add_ai_message(text)
        session.touch()

    # 提供给判定链使用的上下文
    def get_recent_dialog_lines(
            self,
            session_id: str,
            take_n: int = 10,
            max_chars_per_line: int = 240,
    ) -> List[str]:
        """
        从指定会话中取出最近 N 条消息，转成“单行文本列表”。
        设计上是给 should_reply_langchain 用的：
        - human 消息：原样输出（去首尾空白）
        - ai 消息：前面加 "BOT: "
        - 对每一条做 max_chars_per_line 截断
        """
        session = self.get_or_create_session(session_id)
        messages = session.history.messages[-take_n:]

        lines: List[str] = []
        for msg in messages:
            role = getattr(msg, "type", "")  # "human" / "ai" / "system" ...
            content = (getattr(msg, "content", "") or "").strip()

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

    # 管理工具-
    # 主动清理已过期的会话。
    def cleanup_expired(self) -> None:
        if not self._timeout or self._timeout <= 0:
            return

        now = time.time()
        to_delete = [
            sid
            for sid, session in self._sessions.items()
            if (now - session.last_update_time) > self._timeout
        ]
        for sid in to_delete:
            self._sessions.pop(sid, None)


# session_id 计算工具
def calc_session_id(event: dict) -> str:
    """
    - 群聊:  "group:<group_id>"
    - 私聊:  "user:<user_id>"
    """
    msg_type = event.get("message_type")

    if msg_type == "group":
        gid = event.get("group_id")
        return f"group:{gid}"
    elif msg_type == "private":
        uid = event.get("user_id")
        return f"user:{uid}"
    else:
        raise ValueError(f"unknown message_type: {msg_type!r}, event: {event}")
