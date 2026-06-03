from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.chat_history import BaseChatMessageHistory
from src.qqbot.config.config import SELF_USER_ID


@dataclass
# 单个会话的短期记忆容器
class SessionMemory:
    history: BaseChatMessageHistory = field(default_factory=ChatMessageHistory)
    last_update_time: float = field(default_factory=time.time)
    last_proactive_reply_time: float = 0.0  # 上次主动插话的时间
    is_initialized: bool = False

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
            print(f"⏰ 会话 {session_id} 已过期，清空记忆")
            session = None

        # 创建新会话
        if session is None:
            session = SessionMemory()
            self._sessions[session_id] = session
            print(f"🆕 创建新会话: {session_id}")

        session.touch()
        return session

    async def initialize_with_history(
            self,
            session_id: str,
            messages: List[Dict],
            force: bool = False
    ) -> None:
        session = self.get_or_create_session(session_id)

        # 如果已经初始化且不强制，跳过
        if session.is_initialized and not force:
            return

        # 清空现有历史
        session.history.clear()

        # 填充历史消息
        from langchain_core.messages import HumanMessage, AIMessage
        from src.qqbot.utils.image_uploader import get_image_url_or_fallback

        for msg in messages[-self._context_window:]:
            try:
                user_id = msg.get("user_id")
                message_content = msg.get("message", [])
                sender = msg.get("sender", {})
                nickname = sender.get("nickname", "") or sender.get("card", "")

                # 构建多模态内容列表
                content_parts = []
                text_parts = []  # 用于拼接文本

                for segment in message_content:
                    if isinstance(segment, dict):
                        seg_type = segment.get("type")
                        seg_data = segment.get("data", {})

                        if seg_type == "text":
                            text = seg_data.get("text", "")
                            text_parts.append(text)
                        elif seg_type == "image":
                            # 转换图片 URL，上传到 Worker 或使用 base64
                            image_url = seg_data.get("url")
                            if image_url:
                                image_final_url = await get_image_url_or_fallback(image_url)
                                if image_final_url:
                                    content_parts.append({
                                        "type": "image_url",
                                        "image_url": {"url": image_final_url}
                                    })
                                else:
                                    text_parts.append("[图片获取失败]")
                            else:
                                text_parts.append("[图片]")
                        elif seg_type == "at":
                            qq = seg_data.get("qq", "")
                            if qq == SELF_USER_ID:
                                text_parts.append("(系统提示:对方想和你说话)")
                            else:
                                text_parts.append("(系统提示:对方在和其他人说话)")

                # 拼接文本部分
                if text_parts:
                    full_text = f"{nickname}:{''.join(text_parts)}"
                    content_parts.insert(0, {"type": "text", "text": full_text})

                if not content_parts:
                    continue

                # 判断是用户还是机器人
                if user_id == SELF_USER_ID:
                    # 机器人的消息只保存文本
                    text_only = "".join(p.get("text", "") for p in content_parts if p.get("type") == "text")
                    if text_only:
                        session.history.add_message(AIMessage(content=text_only))
                else:
                    # 用户消息保存多模态内容
                    session.history.add_message(HumanMessage(content=content_parts))

            except Exception as e:
                print(f"⚠️ 处理历史消息失败: {e}")
                continue

        session.is_initialized = True
        print(f"✅ 会话 {session_id} 已初始化，加载 {len(session.history.messages)} 条历史")

    def get_history(self, session_id: str) -> BaseChatMessageHistory:
        session = self.get_or_create_session(session_id)

        all_messages = session.history.messages

        # 如果消息数不超过限制，直接返回
        if len(all_messages) <= self._context_window:
            return session.history

        # 裁剪：只保留最近的消息
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

        from langchain_core.messages import HumanMessage
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
        return session is not None and session.is_initialized

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
        print(f"🔄 手动重置会话: {session_id}")
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
