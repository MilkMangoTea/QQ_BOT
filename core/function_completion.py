import base64
import requests
import urllib.parse
import json
import re
import httpx
from openai import OpenAI
import config
from core.function import out

# 请求构建器
def build_params(type, event, content):
    msg_type = event.get("message_type")
    base = ""
    if type == "text":
        if not content:
            content = "嗯"
        base = {"message": [{"type": "text", "data": {"text": content}}]}
    elif type == "image":
        base = {"message": [{"type": "image", "data": {"file": content, "sub_type": 1, "summary": "[色禽图片]"}}]}
    key = "user_id" if msg_type == "private" else "group_id"
    return {**base, "message_type": msg_type, key: event[key]}

# 图片转换
def url_to_base64(url, timeout=(5,20)):
    """
    返回 data:<mime>;base64,... 或 None（出错时）。
    timeout: (connect_timeout, read_timeout)
    """
    try:
        parsed = urllib.parse.urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"

        headers = {
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/120.0.0.0 Safari/537.36"),
            "Accept": "image/*,*/*;q=0.8",
            "Referer": origin,   # 有些站需要防盗链
        }

        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        content = resp.content

        ct = (resp.headers.get("Content-Type") or "").split(";")[0].lower()
        # 简单的 magic-bytes 嗅探（防止 Content-Type 错误）
        if not ct.startswith("image/"):
            if content.startswith(b"\x89PNG\r\n\x1a\n"):
                ct = "image/png"
            elif content.startswith(b"\xff\xd8\xff"):
                ct = "image/jpeg"
            elif content[:6] in (b"GIF87a", b"GIF89a"):
                ct = "image/gif"
            else:
                print(f"⚠️ 非图片 Content-Type: {resp.headers.get('Content-Type')}")
                return None

        b64 = base64.b64encode(content).decode("utf-8")
        return f"data:{ct};base64,{b64}"

    except requests.exceptions.RequestException as e:
        print(f"⚠️ 请求失败: {e}")
    except Exception as e:
        print(f"⚠️ 处理异常: {e}")
    return None

# 轻量 httpx Client
HTTPX_LIMITS  = httpx.Limits(max_connections=100, max_keepalive_connections=20, keepalive_expiry=20.0)
HTTPX_TIMEOUT = httpx.Timeout(connect=5.0, read=8.0, write=5.0, pool=5.0)
HTTP_CLIENT   = httpx.Client(limits=HTTPX_LIMITS, timeout=HTTPX_TIMEOUT, http2=True)

_ZHIPU = config.LLM.get("ZHIPU", {})
_ZHIPU_NAME = _ZHIPU.get("NAME")
_ZHIPU_URL  = _ZHIPU.get("URL")
_ZHIPU_KEY  = _ZHIPU.get("KEY")

def _extract_text(event) -> str:
    parts = []
    for seg in event.get("message", []):
        if seg.get("type") == "text":
            t = seg.get("data", {}).get("text", "")
            if t:
                parts.append(t)
    return "".join(parts).strip()

def should_reply_via_zhipu(event) -> bool:
    """
    用 ZHIPU 做“是否需要回复”的二分类。
    仅在你的本地规则未命中时调用。
    返回 True/False；异常时保守 False。
    """
    if not (_ZHIPU_NAME and _ZHIPU_URL and _ZHIPU_KEY):
        out("ZHIPU 未配置，跳过判定", 400)
        return False

    text = _extract_text(event)
    if not text:
        return False

    msg_type = event.get("message_type")
    gid = event.get("group_id", "")
    uid = event.get("user_id", "")

    system_prompt = (
        "你是一个路由器，只判断机器人是否应该回复这条消息。"
        "只输出 JSON：{\"should_reply\": true/false}。"
        "规则：明确提问/命令/求助/点名 -> true；与机器人无关的闲聊/复读/灌水 -> false；不确定偏 false。"
    )
    user_prompt = f"【消息】{text}\n【上下文】type={msg_type}, gid={gid}, uid={uid}\n只返回 JSON。"

    try:
        cli = OpenAI(
            api_key=_ZHIPU_KEY,
            base_url=_ZHIPU_URL,
            timeout=4.0,      # 快失败，避免拖住事件循环
            max_retries=0,
            http_client=HTTP_CLIENT,
        )
        resp = cli.chat.completions.create(
            model=_ZHIPU_NAME,
            messages=[
                {"role": "system", "content": [{"type": "text", "text": system_prompt}]},
                {"role": "user",   "content": [{"type": "text", "text": user_prompt}]},
            ],
            temperature=0,
            top_p=1,
        )
        content = resp.choices[0].message.content or ""
        m = re.search(r"\{[\s\S]*\}", content)
        data = json.loads(m.group(0)) if m else {}
        should = bool(data.get("should_reply", False))
        out("ZHIPU 判定:", {"should": should, "text": text[:48]})
        return should
    except Exception as e:
        print(f"⚠️ ZHIPU 判定失败: {e}")
        return False
