import html
import json
import re
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


MAX_SOURCE_LENGTH = 16000
MAX_IMAGE_WIDTH = 1600
MAX_IMAGE_HEIGHT = 10000
MAX_PNG_BYTES = 8 * 1024 * 1024
RENDER_TIMEOUT_SECONDS = 20
_SVG_EXTERNAL_URL_RE = re.compile(
    r"(?:href\s*=\s*['\"]\s*(?:https?:|file:|//|javascript:)|"
    r"url\(\s*['\"]?\s*(?:https?:|file:|//|javascript:))",
    re.IGNORECASE,
)
_SVG_BLOCKED_TAGS = {"script", "foreignobject", "iframe", "object", "embed"}


def render_content_png(content: str, content_format: str, output_dir: Path):
    """Render supported text or vector input to a temporary PNG and return its ID and path."""
    if not isinstance(content, str) or not content.strip():
        raise ValueError("渲染内容不能为空")
    if len(content) > MAX_SOURCE_LENGTH:
        raise ValueError(f"渲染内容不能超过 {MAX_SOURCE_LENGTH} 个字符")

    content_format = (content_format or "").strip().lower()
    if content_format not in {"latex", "md", "markdown", "svg"}:
        raise ValueError("格式仅支持 latex、markdown 或 svg")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cleanup_stale_rendered_images(output_dir)

    artifact_id = uuid.uuid4().hex
    output_path = output_dir / f"render_{artifact_id}.png"
    try:
        # 独立进程使超时能真正停止渲染，也隔离 Matplotlib 的全局状态。
        try:
            result = subprocess.run(
                [sys.executable, str(Path(__file__).resolve())],
                input=json.dumps({"content": content, "format": content_format,
                                  "output_path": str(output_path.resolve())}),
                capture_output=True, text=True, timeout=RENDER_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            raise ValueError("渲染超时，请简化内容后重试") from None
        if result.returncode:
            try:
                error = json.loads(result.stdout)["error"]
            except (ValueError, KeyError):
                error = "渲染进程异常退出，请检查渲染依赖"
            raise ValueError(error)

        with Image.open(output_path) as rendered:
            width, height = rendered.size
            if width > MAX_IMAGE_WIDTH or height > MAX_IMAGE_HEIGHT:
                raise ValueError("渲染结果尺寸超出限制")
        if output_path.stat().st_size > MAX_PNG_BYTES:
            raise ValueError("渲染结果文件过大")
        return artifact_id, output_path
    except Exception:
        output_path.unlink(missing_ok=True)
        raise


def get_rendered_image_path(output_dir: Path, artifact_id: str):
    """Resolve an opaque attachment ID without accepting arbitrary filesystem paths."""
    try:
        normalized_id = uuid.UUID(hex=artifact_id).hex
    except (ValueError, TypeError, AttributeError):
        return None
    return Path(output_dir) / f"render_{normalized_id}.png"


def collect_rendered_image_ids(messages):
    """Collect rendered image IDs from structured tool artifacts."""
    found = []
    for message in messages or []:
        if getattr(message, "type", None) != "tool":
            continue
        artifact = getattr(message, "artifact", None)
        if not isinstance(artifact, dict) or artifact.get("type") != "rendered_image":
            continue
        try:
            artifact_id = uuid.UUID(hex=artifact.get("id", "")).hex
        except (ValueError, TypeError, AttributeError):
            continue
        if artifact_id not in found:
            found.append(artifact_id)
    return found


def cleanup_stale_rendered_images(output_dir: Path, max_age_seconds: int = 86400):
    cutoff = time.time() - max_age_seconds
    for path in Path(output_dir).glob("render_*.png"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            pass


def _render_latex(content: str, output_path: Path):
    from matplotlib.mathtext import math_to_image

    expression = content.strip()
    if len(expression) > 4000:
        raise ValueError("LaTeX 数学公式不能超过 4000 个字符")
    if expression.startswith("$$") and expression.endswith("$$"):
        expression = expression[2:-2].strip()
    elif expression.startswith("$") and expression.endswith("$"):
        expression = expression[1:-1].strip()
    elif (expression.startswith(r"\[") and expression.endswith(r"\]")) or (
        expression.startswith(r"\(") and expression.endswith(r"\)")
    ):
        expression = expression[2:-2].strip()
    if not expression:
        raise ValueError("LaTeX 数学公式不能为空")
    from matplotlib.font_manager import FontProperties
    from matplotlib.mathtext import MathTextParser

    font = FontProperties(size=18)
    parsed = MathTextParser("path").parse(f"${expression}$", dpi=180, prop=font)
    if parsed.width + 48 > MAX_IMAGE_WIDTH or parsed.height + 48 > MAX_IMAGE_HEIGHT:
        raise ValueError("LaTeX 渲染结果尺寸超出限制")
    math_to_image(f"${expression}$", str(output_path), prop=font, dpi=180,
                  format="png", color="#202124")
    with Image.open(output_path) as image:
        formula = image.convert("RGBA")
    canvas = Image.new("RGB", (formula.width + 48, formula.height + 48), "white")
    canvas.paste(formula, (24, 24), formula)
    canvas.save(output_path, format="PNG")


def _render_markdown(content: str, output_path: Path):
    width = 1200
    padding = 64
    content_width = width - padding * 2
    font_path = Path("fortune_resources/font/sakura.ttf")
    code_font_path = Path("/System/Library/Fonts/Menlo.ttc")

    def load_font(size, code=False):
        candidates = [code_font_path, font_path] if code else [font_path]
        candidates.extend([Path("/System/Library/Fonts/PingFang.ttc"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")])
        for candidate in candidates:
            if candidate.is_file():
                try:
                    return ImageFont.truetype(str(candidate), size)
                except OSError:
                    continue
        return ImageFont.load_default()

    code_font = load_font(27, code=True)
    code_fallback_font = load_font(27)
    blocks = []
    paragraph = []
    code_lines = []
    in_code = False

    def flush_paragraph():
        if paragraph:
            text = " ".join(part.strip() for part in paragraph if part.strip())
            if text:
                blocks.append((text, 32, "body"))
            paragraph.clear()

    for raw_line in content.splitlines():
        line = raw_line.rstrip()
        if line.strip().startswith("```") or line.strip().startswith("~~~"):
            flush_paragraph()
            if in_code:
                blocks.append(("\n".join(code_lines), 27, "code"))
                code_lines.clear()
                in_code = False
            else:
                in_code = True
            continue
        if in_code:
            code_lines.append(line)
            continue
        if not line.strip():
            flush_paragraph()
            continue

        heading = re.match(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$", line)
        bullet = re.match(r"^\s*([-*+] |\d+[.)] )(.*)$", line)
        quote = re.match(r"^\s*>\s?(.*)$", line)
        if heading:
            flush_paragraph()
            level = len(heading.group(1))
            blocks.append((heading.group(2), max(27, 46 - level * 3), "heading"))
        elif bullet:
            flush_paragraph()
            prefix = bullet.group(1).strip()
            marker = "•" if prefix in {"-", "*", "+"} else prefix
            blocks.append((f"{marker}  {bullet.group(2)}", 32, "body"))
        elif quote:
            flush_paragraph()
            blocks.append((f"│  {quote.group(1)}", 30, "quote"))
        elif re.match(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$", line):
            flush_paragraph()
            blocks.append(("────────", 28, "rule"))
        else:
            paragraph.append(line)

    flush_paragraph()
    if code_lines:
        blocks.append(("\n".join(code_lines), 27, "code"))

    if not blocks:
        raise ValueError("Markdown 中没有可渲染内容")

    draw_probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    layout = []
    y = padding
    for text, size, kind in blocks:
        font = code_font if kind == "code" else load_font(size)
        text = text.expandtabs(4) if kind == "code" else _markdown_inline_text(text)
        if kind == "code":
            lines = []
            for source_line in text.splitlines():
                lines.extend(_wrap_text(source_line, font, draw_probe, content_width, code_fallback_font))
        else:
            lines = _wrap_text(text, font, draw_probe, content_width)
        font_heights = [font.getbbox("Ag")[3] - font.getbbox("Ag")[1]]
        if kind == "code":
            font_heights.append(code_fallback_font.getbbox("中")[3] - code_fallback_font.getbbox("中")[1])
        line_height = max(size + 12, max(font_heights) + 10)
        if kind == "heading":
            y += 24
        if kind == "code":
            y += 12
        for wrapped_line in lines:
            if len(layout) >= 1000:
                raise ValueError("Markdown 渲染行数超出限制")
            layout.append((wrapped_line, font, kind, y, line_height))
            y += line_height
        y += 14 if kind != "code" else 20

    height = min(MAX_IMAGE_HEIGHT, y + padding)
    if y + padding > MAX_IMAGE_HEIGHT:
        raise ValueError("Markdown 渲染结果过长")
    image = Image.new("RGB", (width, height), "#ffffff")
    draw = ImageDraw.Draw(image)
    for text, font, kind, line_y, line_height in layout:
        if kind == "code":
            draw.rounded_rectangle(
                (padding - 12, line_y - 4, width - padding + 12, line_y + line_height - 2),
                radius=6,
                fill="#f1f3f4",
            )
            color = "#202124"
        elif kind == "quote":
            color = "#52616b"
        elif kind == "rule":
            color = "#8b949e"
        else:
            color = "#202124"
        if kind == "code":
            _draw_code_line(draw, (padding, line_y), text, font, code_fallback_font, color)
        else:
            draw.text((padding, line_y), text, font=font, fill=color)
    image.save(output_path, format="PNG", optimize=True)


def _markdown_inline_text(text: str):
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"[图片: \1]", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"<[^>]*>", "", text)
    text = re.sub(r"(?<!\\)(\*\*|__|~~|\*|_)(.*?)\1", r"\2", text)
    text = text.replace("\\*", "*").replace("\\_", "_")
    return html.unescape(text)


def _wrap_text(text, font, draw, max_width, fallback_font=None):
    lines = []
    current = ""
    for char in text:
        candidate = current + char
        if current and _text_width(candidate, font, draw, fallback_font) > max_width:
            lines.append(current)
            current = char
        else:
            current = candidate
    if current or not lines:
        lines.append(current)
    return lines


def _text_width(text, font, draw, fallback_font=None):
    if fallback_font is None:
        return draw.textlength(text, font=font)
    return sum(
        draw.textlength(char, font=_font_for_char(char, font, fallback_font))
        for char in text
    )


def _font_for_char(char, primary_font, fallback_font):
    codepoint = ord(char)
    if 0x2E80 <= codepoint <= 0x9FFF or 0xF900 <= codepoint <= 0xFAFF:
        return fallback_font
    return primary_font


def _draw_code_line(draw, position, text, primary_font, fallback_font, fill):
    x, y = position
    for char in text:
        font = _font_for_char(char, primary_font, fallback_font)
        draw.text((x, y), char, font=font, fill=fill)
        x += draw.textlength(char, font=font)


def _render_svg(content: str, output_path: Path):
    if len(content.encode("utf-8")) > 1024 * 1024:
        raise ValueError("SVG 内容不能超过 1 MB")
    lowered = content.lower()
    if "<!doctype" in lowered or "<!entity" in lowered or "xml-stylesheet" in lowered:
        raise ValueError("SVG 不允许 DTD、实体或外部样式表")

    try:
        root = ET.fromstring(content)
    except ET.ParseError as error:
        raise ValueError("SVG 格式无效") from error
    if root.tag.rsplit("}", 1)[-1].lower() != "svg":
        raise ValueError("输入根节点必须是 SVG")

    for index, element in enumerate(root.iter()):
        if index >= 5000:
            raise ValueError("SVG 元素数量超出限制")
        tag = element.tag.rsplit("}", 1)[-1].lower()
        if tag in _SVG_BLOCKED_TAGS:
            raise ValueError("SVG 包含不允许的活动内容")
        for name, value in element.attrib.items():
            if name.rsplit("}", 1)[-1].lower() in {"href", "src"} and value.strip() and not value.strip().startswith("#"):
                raise ValueError("SVG 不允许外部资源")
            if _SVG_EXTERNAL_URL_RE.search(f"{name}={value}"):
                raise ValueError("SVG 不允许外部资源")
    if "@import" in lowered or _SVG_EXTERNAL_URL_RE.search(content):
        raise ValueError("SVG 不允许外部资源")

    width = _svg_dimension(root.attrib.get("width"))
    height = _svg_dimension(root.attrib.get("height"))
    viewbox = root.attrib.get("viewBox") or root.attrib.get("viewbox")
    if viewbox:
        try:
            _, _, view_width, view_height = [float(value) for value in re.split(r"[ ,]+", viewbox.strip())]
            if view_width <= 0 or view_height <= 0:
                raise ValueError
            width = width or view_width
            height = height or view_height
        except ValueError:
            raise ValueError("SVG viewBox 无效")
    width = width or 1200
    height = height or width
    scale = min(MAX_IMAGE_WIDTH / width, MAX_IMAGE_HEIGHT / height)
    output_width = max(1, min(MAX_IMAGE_WIDTH, int(width * scale)))
    output_height = max(1, min(MAX_IMAGE_HEIGHT, int(height * scale)))

    from cairosvg.surface import PNGSurface

    PNGSurface.convert(
        bytestring=ET.tostring(root, encoding="utf-8"),
        write_to=str(output_path),
        output_width=output_width,
        output_height=output_height,
        unsafe=False,
        url_fetcher=_reject_svg_resource,
        background_color="#ffffff",
    )


def _svg_dimension(value):
    if not value:
        return None
    match = re.fullmatch(r"\s*(\d+(?:\.\d*)?|\.\d+)\s*(px|pt|pc|in|cm|mm)?\s*", value, re.IGNORECASE)
    if not match:
        return None
    number = float(match.group(1))
    unit = (match.group(2) or "px").lower()
    factors = {"px": 1, "pt": 96 / 72, "pc": 16, "in": 96, "cm": 96 / 2.54, "mm": 96 / 25.4}
    return number * factors[unit] if number > 0 else None


def _reject_svg_resource(url, resource_type):
    raise ValueError("SVG 不允许读取外部资源")


if __name__ == "__main__":
    try:
        request = json.load(sys.stdin)
        renderers = {"latex": _render_latex, "svg": _render_svg,
                     "md": _render_markdown, "markdown": _render_markdown}
        renderers[request["format"]](request["content"], Path(request["output_path"]))
    except Exception as error:
        message = str(error) if isinstance(error, ValueError) else "渲染失败，请检查输入和渲染依赖"
        print(json.dumps({"error": message}))
        sys.exit(1)
