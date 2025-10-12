import os
import random
import datetime
import requests

# ---------- Utils ----------
def _rand_pick(items):
    return items[0] if len(items) == 1 else random.choice(items) if items else None

def _days_ago(n):
    return (datetime.datetime.utcnow() - datetime.timedelta(days=n)).date().isoformat()

# ---------- Danbooru ----------
# Docs: https://github.com/danbooru/danbooru/blob/master/doc/api.txt
DANBASE = "https://danbooru.donmai.us/posts.json"

def fetch_danbooru_one(tags, recent_days=14, rating="e"):
    """
    从 Danbooru 取一张：默认限定最近 n 天、优先原图 file_url，不行就 large_file_url
    R-18: rating='e' (explicit) / 'q' (questionable) / 's' (safe)
    """
    qtags = list(tags)
    if rating:
        qtags.append(f"rating:{rating}")
    # 只取最近 n 天，保证“新”
    qtags.append(f"date:>={_days_ago(recent_days)}")
    # 拿一批最新，再本地随机
    params = {
        "tags": " ".join(qtags + ["order:id_desc"]),
        "limit": 100
    }
    r = requests.get(DANBASE, params=params, timeout=12)
    r.raise_for_status()
    posts = r.json()
    if not posts:
        return None
    pick = _rand_pick(posts)
    return pick.get("file_url") or pick.get("large_file_url") or pick.get("preview_file_url")

# ---------- yande.re (Moebooru) ----------
# Docs: https://yande.re/help/api , v2: https://yande.re/post.json?api_version=2
YANBASE = "https://yande.re/post.json"

def fetch_yandere_one(tags, recent_days=14, rating="e"):
    """
    yande.re v2 JSON，按最新抓一批再随机
    rating: 's'/'q'/'e'；Moebooru风格
    """
    qtags = list(tags)
    if rating:
        qtags.append(f"rating:{rating}")
    params = {
        "api_version": 2,
        "tags": " ".join(qtags),
        "limit": 100,         # 拿一批
        "page": 1             # id_desc 默认最新
    }
    r = requests.get(YANBASE, params=params, timeout=12)
    r.raise_for_status()
    posts = r.json()
    if not posts:
        return None
    pick = _rand_pick(posts)
    # v2 字段可能是 'file_url' / 'jpeg_url' / 'sample_url'
    return pick.get("file_url") or pick.get("jpeg_url") or pick.get("sample_url")

# ---------- Gelbooru (HTTP 直调) ----------
# Many clients exist; here use simple REST to avoid extra deps.
GELBASE = "https://gelbooru.com/index.php"

def fetch_gelbooru_one(tags, recent_days=14, rating="explicit"):
    """
    Gelbooru JSON API，取最新一批后随机
    rating 可用: 'safe'/'questionable'/'explicit'
    """
    qtags = list(tags)
    if rating:
        qtags.append(f"rating:{rating}")
    # Gelbooru 不支持直接 date:>= ，用索引顺序取最近（pid=0, 减少limit后本地随机）
    params = {
        "page": "dapi",
        "s": "post",
        "q": "index",
        "json": 1,
        "limit": 100,
        "tags": " ".join(qtags) + " sort:date:desc"
    }
    r = requests.get(GELBASE, params=params, timeout=12, headers={"User-Agent":"qq-bot/1.0"})
    r.raise_for_status()
    posts = r.json() if r.headers.get("Content-Type","").startswith("application/json") else []
    if not posts:
        return None
    pick = _rand_pick(posts)
    return pick.get("file_url") or pick.get("source") or pick.get("preview_url")

# ---------- Lolicon API ----------
# Docs: https://docs.api.lolicon.app/
LOLI = "https://api.lolicon.app/setu/v2"

def fetch_lolicon_one(tags, r18=True, exclude_ai=False):
    """
    Lolicon 官方 API，返回原图 urls.original
    r18: True 使用 r18=1
    """
    params = {
        "r18": 1 if r18 else 0,
        "num": 1,
    }
    if tags:
        params["tag"] = tags  # 支持列表
    if exclude_ai:
        params["excludeAI"] = True
    r = requests.get(LOLI, params=params, timeout=12)
    r.raise_for_status()
    data = r.json().get("data", [])
    if not data:
        return None
    it = data[0]
    urls = it.get("urls") or {}
    return urls.get("original") or urls.get("regular") or urls.get("small")

# ---------- Unified entry ----------
def fetch_acg_one(tags, prefer=("danbooru","yandere","gelbooru","lolicon"), r18=True):
    """
    统一入口：按优先级尝试；返回 str(url) 或 None
    """
    # R-18 映射
    dan_rating = "e" if r18 else "s"
    yan_rating = "e" if r18 else "s"
    gel_rating = "explicit" if r18 else "safe"

    for src in prefer:
        try:
            if src == "danbooru":
                url = fetch_danbooru_one(tags, rating=dan_rating)
            elif src == "yandere":
                url = fetch_yandere_one(tags, rating=yan_rating)
            elif src == "gelbooru":
                url = fetch_gelbooru_one(tags, rating=gel_rating)
            elif src == "lolicon":
                url = fetch_lolicon_one(tags, r18=r18)
            else:
                continue
            if url:
                return url, src
        except Exception:
            continue
    return None, None
