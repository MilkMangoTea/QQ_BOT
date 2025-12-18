import base64
import httpx
import os
from pathlib import Path
from typing import Optional, Union

async def upload_image_bytes_to_worker(
    image_data: bytes,
    filename: Optional[str] = None
) -> Optional[str]:
    """
    上传字节流图片到 Cloudflare Worker

    Args:
        image_data: Raw image bytes
        filename: Optional filename (not used currently)

    Returns:
        Uploaded image URL, or None if failed
    """
    worker_url = os.getenv("WORKER_URL")
    worker_api_key = os.getenv("API_KEY")

    if not worker_url or not worker_api_key:
        return None

    try:
        # 转换为 base64 数据 URI
        b64_data = base64.b64encode(image_data).decode('utf-8')

        if image_data.startswith(b'\x89PNG\r\n\x1a\n'):
            mime_type = 'image/png'
        elif image_data.startswith(b'\xff\xd8\xff'):
            mime_type = 'image/jpeg'
        elif image_data[:6] in (b'GIF87a', b'GIF89a'):
            mime_type = 'image/gif'
        elif image_data.startswith(b'RIFF') and image_data[8:12] == b'WEBP':
            mime_type = 'image/webp'
        else:
            mime_type = 'image/png'

        data_uri = f"data:{mime_type};base64,{b64_data}"

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                worker_url,
                json={"url": data_uri},
                headers={"Authorization": f"Bearer {worker_api_key}"}
            )
            response.raise_for_status()

            result = response.json()
            if result.get("success"):
                print(f"✅ [Worker] 图片上传成功: {result.get('url')}")
                return result.get("url")
            else:
                print(f"⚠️ [Worker] 上传失败: {result}")
                return None

    except httpx.TimeoutException:
        print("⚠️ [Worker] 上传超时")
        return None
    except httpx.HTTPStatusError as e:
        print(f"⚠️ [Worker] HTTP错误 {e.response.status_code}")
        return None
    except Exception as e:
        print(f"⚠️ [Worker] 上传异常: {e}")
        return None


async def upload_image_url_to_worker(image_url: str) -> Optional[str]:
    """
    上传图片 url 到 Cloudflare Worker

    Args:
        image_url: Source image URL (http/https or data URI)

    Returns:
        Uploaded image CDN URL, or None if failed
    """
    worker_url = os.getenv("WORKER_URL")
    worker_api_key = os.getenv("API_KEY")

    if not worker_url or not worker_api_key:
        return None

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                worker_url,
                json={"url": image_url},
                headers={"Authorization": f"Bearer {worker_api_key}"}
            )
            response.raise_for_status()

            result = response.json()
            if result.get("success"):
                print(f"✅ [Worker] URL上传成功: {result.get('url')}")
                return result.get("url")
            else:
                print(f"⚠️ [Worker] URL上传失败: {result}")
                return None

    except httpx.TimeoutException:
        print("⚠️ [Worker] URL上传超时")
        return None
    except httpx.HTTPStatusError as e:
        print(f"⚠️ [Worker] HTTP错误 {e.response.status_code}")
        return None
    except Exception as e:
        print(f"⚠️ [Worker] URL上传异常: {e}")
        return None


def bytes_to_base64_uri(image_data: bytes) -> str:
    """
    转换为模型可读的 base64 数据 URI（标准格式）
    Args:
        image_data: Raw image bytes

    Returns:
        "data:image/...;base64,..." formatted string (OpenAI compatible)
    """
    b64_data = base64.b64encode(image_data).decode('utf-8')

    # 检测 MIME 类型
    if image_data.startswith(b'\x89PNG\r\n\x1a\n'):
        mime_type = 'image/png'
    elif image_data.startswith(b'\xff\xd8\xff'):
        mime_type = 'image/jpeg'
    elif image_data[:6] in (b'GIF87a', b'GIF89a'):
        mime_type = 'image/gif'
    elif image_data.startswith(b'RIFF') and image_data[8:12] == b'WEBP':
        mime_type = 'image/webp'
    else:
        mime_type = 'image/png'

    return f"data:{mime_type};base64,{b64_data}"


async def get_image_url_or_fallback(
    image_source: Union[bytes, str, Path]
) -> str:
    """
    全局图片处理器，上传至 Worker，失败则回退到 base64
    允许多种输入:
    - bytes: Direct upload to Worker, fallback to base64
    - str (URL): Upload via Worker proxy, fallback to base64 (download first)
    - Path: Read file and upload to Worker, fallback to base64

    Args:
        image_source: bytes (raw image), str (URL), or Path (local file)

    Returns:
        Either "https://..." (Worker CDN URL) or "base64://..." (fallback)
    """
    image_bytes = None

    if isinstance(image_source, bytes):
        image_bytes = image_source
    elif isinstance(image_source, Path):
        with open(image_source, 'rb') as f:
            image_bytes = f.read()
    elif isinstance(image_source, str):
        # URL
        if image_source.startswith(('http://', 'https://')):
            uploaded_url = await upload_image_url_to_worker(image_source)
            if uploaded_url:
                return uploaded_url

            try:
                print("⚠️ [Fallback] Worker上传失败，下载图片并使用base64")
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(
                        image_source,
                        headers={
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                        },
                        follow_redirects=True
                    )
                    response.raise_for_status()
                    image_bytes = response.content
            except Exception as e:
                print(f"⚠️ [Fallback] 下载图片失败: {e}")
                return image_source
        else:
            try:
                with open(image_source, 'rb') as f:
                    image_bytes = f.read()
            except Exception as e:
                print(f"⚠️ 读取文件失败: {e}")
                return f"base64://error"

    # 使用 base64 上传到 Worker
    if image_bytes:
        uploaded_url = await upload_image_bytes_to_worker(image_bytes)
        if uploaded_url:
            return uploaded_url

        print("⚠️ [Fallback] 使用base64发送")
        return bytes_to_base64_uri(image_bytes)

    # 所有措施均失效
    return "base64://error"
