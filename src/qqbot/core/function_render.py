import traceback

from langchain_core.tools import tool

from src.qqbot.core.function_fortune import OUT_PATH
from src.qqbot.utils.console import out
from src.qqbot.utils.content_renderer import (
    collect_rendered_image_ids,
    get_rendered_image_path,
    render_content_png,
)
from src.qqbot.utils.image_uploader import get_image_url_or_fallback, to_onebot_image_file


@tool("render_to_png", response_format="content_and_artifact")
def render_to_png(content: str, format: str) -> tuple:
    """Create and send a PNG from LaTeX math, basic Markdown, or SVG source.

    For requests to draw/create an SVG image, generate the SVG source yourself and
    call this tool with format='svg'. The user need not provide source code or say
    'render'. Rendering is local and needs no web search or network connection.
    Only return source code directly when the user explicitly requests code only.

    LaTeX uses Matplotlib mathtext: fractions, roots, sums, integrals, Greek letters,
    superscripts and subscripts. Full TeX documents and begin/end environments are
    unsupported. Markdown supports headings, lists, quotes, links and code blocks.
    Images and external resources are not loaded.

    Args:
        content: The source text or SVG markup to render.
        format: One of latex, markdown, md, or svg.
    """
    out("render_to_png 开始", f"format={format}, chars={len(content)}")
    try:
        artifact_id, path = render_content_png(content, format, OUT_PATH)
        out("render_to_png 成功", f"format={format}, bytes={path.stat().st_size}")
        return "PNG 已生成，将作为图片附件发送。", {"type": "rendered_image", "id": artifact_id}
    except Exception as error:
        out("render_to_png 失败", traceback.format_exc())
        if isinstance(error, ValueError):
            return f"渲染失败：{error}", {}
        return f"渲染失败：{type(error).__name__}，请检查输入或渲染依赖。", {}


def rendered_image_path(artifact_id: str):
    return get_rendered_image_path(OUT_PATH, artifact_id)


def rendered_image_ids(messages):
    return collect_rendered_image_ids(messages)


def cleanup_rendered_images(image_ids):
    for image_id in image_ids:
        path = rendered_image_path(image_id)
        if path is not None:
            try:
                path.unlink(missing_ok=True)
            except OSError as error:
                out("⚠️ 清理未发送的渲染图片失败", error)


async def build_rendered_image_segments(image_ids):
    """Prepare OneBot image segments; only generated files are eligible for cleanup."""
    paths = [rendered_image_path(image_id) for image_id in image_ids]
    paths = [path for path in paths if path is not None]
    segments = []
    try:
        for path in paths:
            try:
                if not path.is_file():
                    out("⚠️ 渲染图片文件不存在", path.name)
                    continue
                image_file = to_onebot_image_file(await get_image_url_or_fallback(path))
                if image_file:
                    segments.append({"type": "image", "data": {"file": image_file}})
            except Exception as error:
                out("⚠️ 准备渲染图片失败", error)
    finally:
        # 段内已经是 URL 或图片数据，发送和重试不再需要本地文件。
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError as error:
                out("⚠️ 清理临时渲染图片失败", error)
    return segments
