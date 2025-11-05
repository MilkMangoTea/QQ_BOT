import base64
import requests
import urllib.parse
import json
import re
import httpx
from openai import OpenAI
import config

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
HTTPX_TIMEOUT = httpx.Timeout(connect=10.0, read=25.0, write=10.0, pool=10.0)
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

def should_reply_via_zhipu(event, handle_pool) -> bool:
    if not (_ZHIPU_NAME and _ZHIPU_URL and _ZHIPU_KEY):
        print("400 ZHIPU 未配置，跳过判定")
        return False

    curr_text = _extract_text(event)
    if not curr_text:
        return False

    take_n = 5
    raw = list(handle_pool or [])[-take_n:]
    ctx_lines = []
    for s in raw:
        # 兼容 dict/str 两种：如果是 dict，则优先取 "text"
        if isinstance(s, dict):
            s = s.get("text") if "text" in s else str(s)
        s = (s or "").strip()
        if not s:
            continue

        # 判断是否是“昵称：内容”/“昵称:内容”格式（别人说话）
        if re.match(r'^[^：:]{1,24}[：:]', s):
            line = s
        else:
            line = f"BOT: {s}"
        if len(line) > 240:
            line = line[:240] + "…"
        ctx_lines.append(line)

    # 上下文按时间正序
    ctx_block = "\n".join(ctx_lines) if ctx_lines else "（无）"

    system_prompt = (
        "你是群聊路由器，判断机器人是否应回复‘当前消息’。\n"
        "严格只输出 JSON："
        "{\"should_reply\": true/false, \"category\": \"DIRECT_AT|FOLLOWUP|QUESTION|COMMAND|CHITCHAT|NOISE|OTHER\", \"confidence\": 0~1}\n"
        "判定指导：\n"
        "A) 上下文中行首为“BOT: ”的是机器人历史发言；行首为“昵称：”或“昵称:”的是群友发言。\n"
        "B) 如果当前消息与机器人上一轮内容强相关的追问/澄清/继续 -> true；\n"
        "C) 明确的问题/请求/命令 -> true；\n"
        "D) 口水、灌水、纯表情/复读、与机器人无关 -> false；\n"
        "E) 不确定偏 false。"
    )

    user_prompt = (
        f"【群聊最近上下文】\n{ctx_block}\n\n"
        f"【当前消息】\n{curr_text}\n"
        f"【元信息】type={event.get('message_type')}, gid={event.get('group_id')}, uid={event.get('user_id')}\n"
        "只返回 JSON。"
    )

    try:
        cli = OpenAI(
            api_key=_ZHIPU_KEY,
            base_url=_ZHIPU_URL,
            timeout=15.0,
            max_retries=2,
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
            timeout=15.0
        )
        content = (resp.choices[0].message.content or "").strip()
        m = re.search(r"\{[\s\S]*\}", content)
        data = json.loads(m.group(0)) if m else {}
        should = bool(data.get("should_reply", False))
        print("ZHIPU 判定:", {
            "should": should,
            "cat": data.get("category"),
            "conf": data.get("confidence"),
            "curr": curr_text[:48]
        })
        return should
    except Exception as e:
        print(f"⚠️ ZHIPU 判定失败: {e}")
        return False

