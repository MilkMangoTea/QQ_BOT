import os
import random
import datetime
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ========== Proxy & Session ==========
PROXY_URL = os.environ.get("ACG_PROXY", "http://127.0.0.1:7890")
DEFAULT_TIMEOUT = 12  # 统一超时

def _build_session(proxy_url=PROXY_URL, timeout=DEFAULT_TIMEOUT):
    s = requests.Session()
    # 统一代理
    if proxy_url:
        s.proxies.update({
            "http": proxy_url,
            "https": proxy_url,
        })
    # 统一 UA
    s.headers.update({"User-Agent": "acg-fetcher/1.0"})
    # 失败重试（对网络波动更稳）
    retry = Retry(
        total=3,
        backoff_factor=0.6,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods={"GET", "HEAD", "OPTIONS"},
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("http://", adapter)
    s.mount("https://", adapter)

    # 包一层默认 timeout
    _request = s.request
    def _request_with_timeout(method, url, **kwargs):
        kwargs.setdefault("timeout", timeout)
        return _request(method, url, **kwargs)
    s.request = _request_with_timeout
    return s

SESSION = _build_session()

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
    qtags.append(f"date:>={_days_ago(recent_days)}")
    params = {
        "tags": " ".join(qtags + ["order:id_desc"]),
        "limit": 100
    }
    r = SESSION.get(DANBASE, params=params)
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
    r = SESSION.get(YANBASE, params=params)
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
    params = {
        "page": "dapi",
        "s": "post",
        "q": "index",
        "json": 1,
        "limit": 100,
        "tags": " ".join(qtags) + " sort:date:desc"
    }
    r = SESSION.get(GELBASE, params=params, headers={"User-Agent": "qq-bot/1.0"})
    # ↑ 已有全局 UA，这里保留原实现；也可省略此 headers
    if r.headers.get("Content-Type", "").startswith("application/json"):
        posts = r.json()
    else:
        posts = []
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
    r = SESSION.get(LOLI, params=params)
    r.raise_for_status()
    data = r.json().get("data", [])
    if not data:
        return None
    it = data[0]
    urls = it.get("urls") or {}
    return urls.get("original") or urls.get("regular") or urls.get("small")

# ---------- Pixiv (App-API via pixivpy) ----------
# pip install pixivpy
def _build_pixiv_appapi_client():
    try:
        from pixivpy3 import AppPixivAPI
    except ImportError:
        return None, "pixivpy not installed"
    refresh_token = os.environ.get("PIXIV_REFRESH_TOKEN")
    if not refresh_token:
        return None, "PIXIV_REFRESH_TOKEN missing"
    api = AppPixivAPI(proxies={"http": PROXY_URL, "https": PROXY_URL} if PROXY_URL else None, timeout=DEFAULT_TIMEOUT)
    api.auth(refresh_token=refresh_token)
    return api, None

def fetch_pixiv_one(tags, recent_days=14, r18=True, exclude_ai=False):
    """
    Pixiv App-API 搜索：按时间倒序抓一批再随机；返回原图 url
    """
    api, err = _build_pixiv_appapi_client()
    if not api:
        raise RuntimeError(f"Pixiv App-API unavailable: {err}")

    # 搜索词：Pixiv 支持空格分隔 OR/AND，简单起见直接空格 join
    word = " ".join(tags) if tags else ""
    search_target = "partial_match_for_tags"   # 更宽松的标签匹配
    sort = "date_desc"
    # R-18：App-API 用 "search_illust" + word中可含 r-18 标签；后续再二次过滤 x_restrict
    json_result = api.search_illust(word, search_target=search_target, sort=sort)
    illusts = (json_result.illusts or []) if json_result else []
    if not illusts:
        return None

    # 过滤：时间、R18、AI
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=recent_days)
    def _ok(it):
        # x_restrict: 0=safe, 1=R18, 2=R18G
        xr = getattr(it, "x_restrict", 0)
        if r18:
            if xr not in (1, 2):
                return False
        else:
            if xr != 0:
                return False
        if exclude_ai:
            # App-API: illust.ai_type: 0=Not AI, 2=AI
            if getattr(it, "ai_type", 0) == 2:
                return False
        # 时间
        create_date = getattr(it, "create_date", None)
        try:
            dt = datetime.datetime.fromisoformat(create_date.replace("Z","+00:00")).replace(tzinfo=None)
            if dt < cutoff:
                return False
        except Exception:
            pass
        return True

    cand = [it for it in illusts if _ok(it)]
    if not cand:
        return None
    pick = _rand_pick(cand)
    # 原图：在 meta_single_page 或 meta_pages 中
    url = None
    if getattr(pick, "meta_single_page", None) and pick.meta_single_page.get("original_image_url"):
        url = pick.meta_single_page["original_image_url"]
    elif getattr(pick, "meta_pages", None):
        pages = pick.meta_pages
        if pages:
            url = pages[0]["image_urls"].get("original") or pages[0]["image_urls"].get("large")
    if not url and getattr(pick, "image_urls", None):
        url = pick.image_urls.get("large") or pick.image_urls.get("medium")
    return url

# ---------- Unified entry ----------
def fetch_acg_one(tags, prefer=("pixiv","danbooru","yandere","gelbooru","lolicon"), r18=True):
    dan_rating = "e" if r18 else "s"
    yan_rating = "e" if r18 else "s"
    gel_rating = "explicit" if r18 else "safe"

    for src in prefer:
        try:
            print(f"尝试从 {src} 取图...")
            if src == "danbooru":
                url = fetch_danbooru_one(tags, rating=dan_rating)
            elif src == "yandere":
                url = fetch_yandere_one(tags, rating=yan_rating)
            elif src == "gelbooru":
                url = fetch_gelbooru_one(tags, rating=gel_rating)
            elif src == "pixiv":
                url = fetch_pixiv_one(tags, r18=r18)   # <- 新增
            elif src == "lolicon":
                url = fetch_lolicon_one(tags, r18=r18)
            else:
                continue
            if url:
                return url, src
        except Exception as e:
            print(f"⚠️ 从 {src} 取图失败: {e}")
            continue
    return None, None