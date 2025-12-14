import re
from typing import Dict, Optional
from mem0 import Memory
import config

# 初始化 Mem0 客户端
MEMORY = Memory.from_config(config.MEM0_CONFIG)

class LocalDictStore:
    """
    mem0 封装：
    - get(record_id)  -> 从 mem0 拉该用户的所有记忆，拼成一个简单的 {key: value} dict
    - set(record_id, key, value) -> 把单条记忆写到 mem0
    """

    def __init__(self, *args, **kwargs):
        self.m = MEMORY

    def get(self, user_id: str, query: Optional[str] = None, limit: int = 3) -> Dict[str, str]:
        """
        query 有就 search；没有就 get_all
        返回 dict 给 dic_to_prompt_list 用
        """
        user_id = str(user_id)
        if query:
            res = self.m.search(query, user_id=user_id, limit=limit)
        else:
            res = self.m.get_all(user_id=user_id)

        items = res.get("results", []) if isinstance(res, dict) else (res or [])
        dic: Dict[str, str] = {}
        for i, it in enumerate(items, start=1):
            text = it.get("memory")
            if text:
                dic[f"mem_{i}"] = text
        return dic

    # mem0 自动抽记忆
    def add_turn(self, user_id: str, user_text: str, assistant_text: str):
        user_id = str(user_id)
        user_text = re.sub(r"^[^:：]{1,30}\s*[:：]\s*", "", user_text).strip()
        messages = [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": assistant_text},
        ]
        self.m.add(messages, user_id=user_id)


# 将字典转化为序列
def dic_to_prompt_list(dic):
    text = ""
    if dic is None:
        return []
    for key, value in dic.items():
        text += f"{key}: {value}\n"
    list = [{"role": "system", "content": [{"type": "text", "text": text}]}]
    return list