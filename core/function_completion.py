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
async def url_to_base64(url, timeout=(5, 20)):
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
            "Referer": origin,  # 有些站需要防盗链
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
HTTPX_LIMITS = httpx.Limits(max_connections=100, max_keepalive_connections=20, keepalive_expiry=20.0)
HTTPX_TIMEOUT = httpx.Timeout(connect=10.0, read=25.0, write=10.0, pool=10.0)
HTTP_CLIENT = httpx.Client(limits=HTTPX_LIMITS, timeout=HTTPX_TIMEOUT, http2=True)

_ZHIPU = config.LLM.get("ZHIPU", {})
_ZHIPU_NAME = _ZHIPU.get("NAME")
_ZHIPU_URL = _ZHIPU.get("URL")
_ZHIPU_KEY = _ZHIPU.get("KEY")


def _extract_text(event) -> str:
    parts = []
    for seg in event.get("message", []):
        if seg.get("type") == "text":
            t = seg.get("data", {}).get("text", "")
            if t:
                parts.append(t)
    return "".join(parts).strip()


async def should_reply_via_zhipu(event, handle_pool_whole) -> bool:
    if not (_ZHIPU_NAME and _ZHIPU_URL and _ZHIPU_KEY):
        print("400 ZHIPU 未配置，跳过判定")
        return False

    curr_text = _extract_text(event)
    if not curr_text:
        return False

    take_n = 5
    ctx_lines = []
    gid = str(event.get("group_id"))
    handle_pool = handle_pool_whole[gid]

    if handle_pool:
        # 取最近 N 条，按时间正序给模型
        for item in reversed(list(handle_pool)[-take_n:]):
            if isinstance(item, dict):
                role = (item.get("role") or "").lower()
                text_line = ""
                if isinstance(item.get("content"), list):
                    parts = []
                    for seg in item["content"]:
                        if isinstance(seg, dict) and seg.get("type") == "text":
                            t = seg.get("text") or ""
                            if t:
                                parts.append(t)
                    text_line = "".join(parts).strip()
                else:
                    text_line = (item.get("text") or "").strip()
            else:
                role = ""
                text_line = str(item).strip()

            if not text_line:
                continue

            # 根据 role 标注：user 行保留，assistant 行加 BOT
            if role == "assistant":
                line = f"BOT: {text_line}"
            else:
                line = text_line

            if len(line) > 240:
                line = line[:240] + "…"
            ctx_lines.append(line)

        ctx_lines.reverse()

    ctx_block = "\n".join(ctx_lines) if ctx_lines else "（无）"

    system_prompt = (
        """
你是一个“群聊消息路由器”，唯一职责：判断机器人是否应该在当前群消息下发言，并给出类别。

【只输出 JSON】
只返回这一行 JSON（键名固定、枚举大写）：
{"should_reply": true/false, "category": "FOLLOWUP|QUESTION|CHITCHAT|OTHER|NOISE", "confidence": 0~1}
不要输出任何解释或额外字符。若不使用置信度，可固定 0.7/0.8/0.9 等离散值。

【上下文说明】
- “BOT: ” 为机器人历史发言；“群友A: / 群友B: / 群友C:” 为群成员发言。
- 仅依据输入中给到的上下文语义进行判断；不要进行计数或推断未提供的信息。

【像普通群友的决策原则（弹性语义）】
1) FOLLOWUP（对 BOT 话语或既有互动约定的自然延续）
   - 语义延续：当前消息与最近的 BOT 话题在语义上紧密相关，并包含追问/澄清/让继续/异议/补充等意图。
   - 互动约定（微协议）：上下文中若出现“当/如果/以后…就…/看到…请…/我说…你…/我发…你…”等**期望机器人按某触发做出回应**的承诺或约定，
     当后续消息语义上**匹配或高度相似**于该触发（允许轻微变体、同义改写、空白/标点差异），视为该约定被触发，应回复。
   - 极短消息（如单词/数字/符号）**若语义上能指向上述约定或延续**，也按 FOLLOWUP；否则不要因为短而默认回复。

2) QUESTION（面向群体的求助/征求意见）
   - 识别群体求助语义（如“有没有人/大家/谁懂/求看下/怎么/为什么/能不能/怎么办”等），即使没有问号也算。
   - 若问题明显非向机器人但机器人能提供有益、简短的意见，也可参与；若是明确的人与人对接且与机器人无关，转 OTHER。

3) CHITCHAT（与当前话题相关的轻社交）
   - 你的介入能自然推进（简短确认、鼓励、收尾、轻建议/指路），**避免专业长篇**。纯寒暄不回。

4) OTHER（人与人侧聊或与机器人无关的协调）
   - 明确点名某个群友进行交接/安排，且与机器人无关时，不插话。

5) NOISE（复读、表情、无意义片段、与上下文完全脱节）
   - 仅当无法与任何话题或互动约定建立清晰语义联系时，判为 NOISE。

【置信度（离散映射，避免“估概率”）】
- FOLLOWUP = 0.9，QUESTION = 0.8，CHITCHAT = 0.65，OTHER/NOISE = 0.8（可按需统一固定为 0.7）。

【few-shot（只用作内部判断，不要在输出中复述）】
示例1（FOLLOWUP·延续）
BOT: 已给出三步操作
群友A: 第2步不明白，能再说说吗
→ {"should_reply": true, "category": "FOLLOWUP", "confidence": 0.9}

示例2（FOLLOWUP·互动约定触发，内容可变体）
群友A: 当我说 <触发词> 时，你简单答复就好
BOT: 明白
群友A: <触发词>   （或轻微变体，如空白/标点差异）
→ {"should_reply": true, "category": "FOLLOWUP", "confidence": 0.9}

示例3（QUESTION）
群友B: 大家有推荐的午餐吗
→ {"should_reply": true, "category": "QUESTION", "confidence": 0.8}

示例4（CHITCHAT）
BOT: 文档链接已发，按步骤执行即可
群友C: 好的我晚上试试
→ {"should_reply": true, "category": "CHITCHAT", "confidence": 0.65}

示例5（OTHER）
群友A: 群友B: 表格今晚前发我
→ {"should_reply": false, "category": "OTHER", "confidence": 0.8}

示例6（NOISE）
群友B: ？
（上下文无明确话题或约定可指向）
→ {"should_reply": false, "category": "NOISE", "confidence": 0.8}

"""
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
                {"role": "user", "content": [{"type": "text", "text": user_prompt}]},
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
            "user_prompt": user_prompt,
            "should": should,
            "cat": data.get("category"),
            "conf": data.get("confidence"),
            "curr": curr_text[:48]
        })
        return should
    except Exception as e:
        print(f"⚠️ ZHIPU 判定失败: {e}")
        return False
