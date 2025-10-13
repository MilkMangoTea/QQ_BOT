import base64
import requests
import os
import io
import urllib.parse
from typing import Optional
from openai import OpenAI

# 请求构建器
def build_params(type, event, content):
    msg_type = event.get("message_type")
    base = ""
    if type == "text":
        if not content:
            content = "ioi"
        base = {"message": [{"type": "text", "data": {"text": content}}]}
    elif type == "image":
        base = {"message": [{"type": "image", "data": {"file": content, "sub_type": 1, "summary": "[色禽图片]"}}]}
    key = "user_id" if msg_type == "private" else "group_id"
    return {**base, "message_type": msg_type, key: event[key]}

# 图片转换(目前准备停用)
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

from config import LLM, CURRENT_COMPLETION
_cfg = LLM[CURRENT_COMPLETION]
API_KEY = _cfg["KEY"]
BASE_URL = _cfg["URL"]
MODEL_NAME = _cfg["NAME"]

# ===== OpenAI 客户端（单例）=====
_client_singleton: Optional[OpenAI] = None
def get_client() -> OpenAI:
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    return _client_singleton

# ===== 进程内缓存：同一 URL 复用 file_id，不重复上传 =====
_URL2FILEID = {}

# ===== 简单工具：下载图片（带 Referer/UA，流式，低内存）=====
def _download_image_bytes(url: str, timeout=(5, 20)) -> bytes:
    parsed = urllib.parse.urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"),
        "Accept": "image/*,*/*;q=0.8",
        "Referer": origin,  # 腾讯系常需要
    }
    with requests.get(url, headers=headers, stream=True, timeout=timeout, allow_redirects=True) as r:
        r.raise_for_status()
        buf = io.BytesIO()
        for chunk in r.iter_content(64 * 1024):
            if chunk: buf.write(chunk)
        return buf.getvalue()

# ===== 猜扩展名（用于给文件起名；猜不中就 .jpg）=====
def _guess_ext(content: bytes, fallback=".jpg") -> str:
    head = content[:12]
    if head.startswith(b"\x89PNG\r\n\x1a\n"): return ".png"
    if head.startswith(b"\xff\xd8\xff"):      return ".jpg"
    if head[:6] in (b"GIF87a", b"GIF89a"):    return ".gif"
    if head.startswith(b"RIFF") and b"WEBP" in head[:12]: return ".webp"
    if head.startswith(b"\x00\x00\x00") and b"ftyp" in content[4:12]: return ".avif"
    return fallback

# ===== 上传为 Files（purpose='vision'）→ 返回 file_id =====
def _upload_bytes_get_file_id(content: bytes, filename_prefix="image") -> str:
    ext = _guess_ext(content)
    filename = f"{filename_prefix}{ext}"
    api = get_client()
    f = api.files.create(
        file=(filename, io.BytesIO(content), "application/octet-stream"),
        purpose="vision"
    )
    return f.id  # 形如 file_xxx

# ===== 确保拿到 file_id（带缓存）=====
def ensure_file_id(url: str, *, force_reupload: bool = False) -> str:
    if not force_reupload and url in _URL2FILEID:
        return _URL2FILEID[url]
    content = _download_image_bytes(url)
    file_id = _upload_bytes_get_file_id(content)
    _URL2FILEID[url] = file_id
    return file_id

# ===== 供 Chat Completions 使用的图片消息（自动：优先 file:，失败回退 data:）=====
def build_image_message_chat_auto(url: str, text: Optional[str]=None, detail="auto") -> dict:
    # 优先：file_id -> "file:FILE_ID"
    try:
        fid = ensure_file_id(url)
        parts = []
        if text: parts.append({"type": "text", "text": text})
        parts.append({"type": "image_url",
                      "image_url": {"url": f"file:{fid}", "detail": detail}})
        return {"role": "user", "content": parts}
    except Exception:
        # 回退：data URL（通用）
        data_url = url_to_base64(url)
        parts = []
        if text: parts.append({"type": "text", "text": text})
        parts.append({"type": "image_url",
                      "image_url": {"url": data_url, "detail": detail}})
        return {"role": "user", "content": parts}