import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import re

class LocalDictStore:
    """
    顶层以 record_id 分组，每个 record_id 对应一个键->值的子字典。
    存盘格式示例：
    {
      "record1": { "k1": "v1", "k2": "v2" },
      "record2": { "foo": "bar" }
    }
    """
    def __init__(self, filepath: str = "memory_store.json"):
        self.filepath = Path(filepath)
        self.data: Dict[str, Dict[Any, Any]] = {}
        if self.filepath.exists():
            self.load()

    def set(self, record_id: str, key: Any, value: Any) -> None:
        """在 record_id 下设置或更新 key=value，并立即保存。"""
        if record_id not in self.data:
            self.data[record_id] = {}
        self.data[record_id][key] = value
        self.save()

    def get(self, record_id: str, key: Any = None, default: Any = None) -> Any:
        """获取某条记录下的单个键，若不存在则返回 default。"""
        if not key:
            return self.data.get(record_id)
        return self.data.get(record_id, {}).get(key, default)

    def get_record(self, record_id: str) -> Dict[Any, Any]:
        """获取整个 record_id 对应的键值字典，若不存在则返回空字典。"""
        return dict(self.data.get(record_id, {}))

    def delete(self, record_id: str, key: Optional[Any] = None) -> None:
        """
        删除操作：
        - 如果未指定 key，则删除整个 record_id。
        - 否则仅删除该 record_id 下的指定 key。
        """
        if record_id not in self.data:
            return
        if key is None:
            del self.data[record_id]
        else:
            self.data[record_id].pop(key, None)
            # 如果子字典空了，也删掉这条记录
            if not self.data[record_id]:
                del self.data[record_id]
        self.save()

    def list_ids(self) -> List[str]:
        """返回所有 record_id 列表。"""
        return list(self.data.keys())

    def list_keys(self, record_id: str) -> List[str]:
        """返回某条记录下的所有键名。"""
        return list(self.data.get(record_id, {}).keys())

    def save(self) -> None:
        """将整个 data 字典序列化到 JSON 文件。"""
        self.filepath.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    def load(self) -> None:
        """从 JSON 文件加载到内存 data。"""
        self.data = json.loads(self.filepath.read_text(encoding="utf-8"))

    def export(self, export_path: str) -> None:
        """导出当前 data 到指定 JSON 文件（备份/迁移）。"""
        Path(export_path).write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    @classmethod
    def import_from(cls, import_path: str) -> "LocalDictStore":
        """从已有 JSON 文件创建新的实例。"""
        return cls(import_path)

# 将字典转化为序列
def dic_to_prompt_list(dic):
    text = ""
    if dic is None:
        return []
    for key, value in dic.items():
        text += f"{key}: {value}\n"
    list = [{"role": "system", "content": [{"type": "text", "text": text}]}]
    return list

# 从回复中提取 key, value
def get_memory(text):
    pattern_tag = re.compile(r'<memory>(.*?)</memory>', re.DOTALL)
    pattern_dic = re.compile(r'key:(?P<key>.*?)\s+value:(?P<value>.*)')

    dic_input = {}
    m_tag = pattern_tag.search(text)

    for m in pattern_dic.finditer(m_tag.group(1)):
        key = m.group("key")
        value = m.group("value")
        dic_input[key] = value

    return dic_input

def memory(response, current_id, memory_pool):
    if "<memory>" not in response:
        return response

    else:
        try:
            current_id = str(current_id)
            dic_input = get_memory(response)
            for k, v in dic_input.items():
                memory_pool.set(current_id, k, v)

            return re.sub(r"<memory>([\s\S]*?)</memory>", "", response).strip()

        except Exception as e:
            print(f"⚠️ memory 错误: {e}")

