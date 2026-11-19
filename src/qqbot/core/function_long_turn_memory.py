import re
import threading
from typing import Dict, Optional
from mem0 import Memory
from src.qqbot.config import config
from src.qqbot.utils.console import out

class LocalDictStore:
    """Mem0 的同步适配层。"""

    def __init__(self, *args, **kwargs):
        self.m = None
        self._init_lock = threading.Lock()
        self._enabled = config.ENABLE_MEM0

    def _get_client(self):
        """返回已初始化的 Mem0 客户端；初始化失败时允许下次请求重试。"""
        if not self._enabled:
            return None

        if self.m is not None:
            return self.m

        with self._init_lock:
            if self.m is None:
                try:
                    self.m = Memory.from_config(config.MEM0_CONFIG)
                    out("✅ Mem0 客户端已就绪")
                except Exception as e:
                    out("⚠️ Mem0 初始化失败", e)
                    raise

        return self.m

    def get(self, user_id: str, query: Optional[str] = None, limit: int = 3) -> Dict[str, str]:
        """按查询文本检索用户记忆。空查询不读取长期记忆。"""
        if not self._enabled:
            return {}

        user_id = str(user_id)
        if not query or not query.strip():
            return {}

        memory = self._get_client()
        if memory is None:
            return {}

        try:
            res = memory.search(query, filters={"user_id": user_id}, limit=limit)
        except TypeError:
            # 兼容支持顶层 user_id 参数的 Mem0 版本。
            res = memory.search(query, user_id=user_id, limit=limit)

        items = res.get("results", []) if isinstance(res, dict) else (res or [])
        dic: Dict[str, str] = {}
        for i, it in enumerate(items, start=1):
            text = it.get("memory")
            if text:
                dic[f"mem_{i}"] = text
        return dic

    def add_turn(self, user_id: str, user_text: str, assistant_text: str):
        """将一轮对话交给 Mem0 提取并保存记忆。"""
        if not self._enabled:
            return

        user_id = str(user_id)
        user_text = re.sub(r"^[^:：]{1,30}\s*[:：]\s*", "", user_text).strip()
        if not user_text or not assistant_text:
            return

        memory = self._get_client()
        if memory is None:
            return

        messages = [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": assistant_text},
        ]
        memory.add(messages, user_id=user_id)


# 将字典转化为序列
def dic_to_prompt_list(dic):
    text = ""
    if dic is None:
        return []
    for key, value in dic.items():
        text += f"{key}: {value}\n"
    messages = [{"role": "system", "content": [{"type": "text", "text": text}]}]
    return messages
