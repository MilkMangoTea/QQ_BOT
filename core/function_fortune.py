import json
import random
from pathlib import Path
from typing import List, Tuple
from PIL import Image, ImageDraw, ImageFont

# ===== 配置 =====

# 资源路径
FORTUNE_PATH = Path("fortune_resources")
IMG_PATH = FORTUNE_PATH / "img"
FONT_PATH = FORTUNE_PATH / "font"
COPYWRITING_PATH = FORTUNE_PATH / "copywriting.json"
OUT_PATH = FORTUNE_PATH / "out"

# 启用的主题
THEME_CONFIG = {
    "hololive": {"enabled": True, "weight": 2},
    "touhou": {"enabled": True, "weight": 5},
    "touhou_lostword": {"enabled": True, "weight": 5},
    "hoshizora": {"enabled": True, "weight": 2},
    "mmt": {"enabled": True, "weight": 1},
    "gura": {"enabled": True, "weight": 4}
}



# 获取运势文案
def get_copywriting() -> Tuple[str, str]:
    try:
        with open(COPYWRITING_PATH, 'r', encoding='utf-8') as f:
            content = json.load(f).get("copywriting", [])

            if not content:
                return "今日运势", "今天也要加油哦！"

            luck = random.choice(content)
            title = luck.get("good-luck", "今日运势")
            text = random.choice(luck.get("content", ["今天也要加油哦！"]))

            return title, text

    except Exception as e:
        print(f"⚠️ 读取文案失败: {e}")
        return "今日运势", "今天也要加油哦！"


# 选择签底图
# 获取所有可用主题
def get_available_themes() -> Tuple[List[str], List[int]]:
    themes = []
    weights = []

    for theme, config in THEME_CONFIG.items():
        if config.get("enabled", False) and (IMG_PATH / theme).exists():
            themes.append(theme)
            weights.append(config.get("weight", 1))

    return themes, weights

# 随机选择一张签底图
def random_basemap(theme: str = "random") -> Path:
    if theme == "random":
        themes, weights = get_available_themes()
        if not themes:
            raise ValueError("没有可用的主题")
        theme = random.choices(themes, weights=weights, k=1)[0]

    # 获取主题文件夹
    theme_path = IMG_PATH / theme
    if not theme_path.exists():
        raise ValueError(f"主题 {theme} 不存在")

    # 获取所有图片
    images = []
    for ext in ['.jpg', '.jpeg', '.png', '.webp']:
        images.extend(theme_path.glob(f'*{ext}'))

    if not images:
        raise ValueError(f"主题 {theme} 没有图片")

    return random.choice(images)


# 文字排版
def decrement(text: str) -> Tuple[int, List[str]]:
    """
    分割文本，返回列数和文本列表
    """
    length = len(text)
    result = []
    cardinality = 9  # 每列最多 9 个字

    if length > 4 * cardinality:
        # 文本过长，截断
        text = text[:4 * cardinality]
        length = len(text)

    col_num = 1
    while length > cardinality:
        col_num += 1
        length -= cardinality

    # 针对两列优化
    space = " "
    length = len(text)

    if col_num == 2:
        if length % 2 == 0:
            # 偶数
            fill_in = space * int(9 - length / 2)
            return col_num, [
                text[:int(length / 2)] + fill_in,
                fill_in + text[int(length / 2):],
            ]
        else:
            # 奇数
            fill_in = space * int(9 - (length + 1) / 2)
            return col_num, [
                text[:int((length + 1) / 2)] + fill_in,
                fill_in + space + text[int((length + 1) / 2):],
            ]

    # 多列情况
    for i in range(col_num):
        if i == col_num - 1 or col_num == 1:
            result.append(text[i * cardinality:])
        else:
            result.append(text[i * cardinality:(i + 1) * cardinality])

    return col_num, result


# 画签
def drawing(theme: str = "random") -> Path:
    """
    生成运势卡片
    :param theme: 主题名称
    :return: 生成的图片路径
    """
    # 随机选择签底图
    img_path = random_basemap(theme)
    img = Image.open(img_path).convert("RGB")
    draw = ImageDraw.Draw(img)

    # 随机选择运势文案
    title, text = get_copywriting()

    # 绘制标题
    font_size = 45
    color = "#F5F5F5"
    image_font_center = [140, 99]

    # 字体路径
    title_font_path = FONT_PATH / "Mamelon.otf"
    text_font_path = FONT_PATH / "sakura.ttf"

    # 如果字体不存在，使用默认字体
    try:
        if title_font_path.exists():
            ttfront = ImageFont.truetype(str(title_font_path), font_size)
        else:
            ttfront = ImageFont.load_default()
    except:
        ttfront = ImageFont.load_default()

    # 获取标题宽度
    try:
        bbox = draw.textbbox((0, 0), title, font=ttfront)
        font_length = (bbox[2] - bbox[0], bbox[3] - bbox[1])
    except:
        font_length = (len(title) * font_size * 0.6, font_size)

    # 绘制标题
    draw.text(
        (
            image_font_center[0] - font_length[0] / 2,
            image_font_center[1] - font_length[1] / 2,
        ),
        title,
        fill=color,
        font=ttfront,
    )

    # 绘制正文
    font_size = 25
    color = "#323232"
    image_font_center = [140, 297]

    try:
        if text_font_path.exists():
            ttfront = ImageFont.truetype(str(text_font_path), font_size)
        else:
            ttfront = ImageFont.load_default()
    except:
        ttfront = ImageFont.load_default()

    slices, result = decrement(text)

    for i in range(slices):
        font_height = len(result[i]) * (font_size + 4)
        text_vertical = "\n".join(result[i])
        x = int(
            image_font_center[0]
            + (slices - 2) * font_size / 2
            + (slices - 1) * 4
            - i * (font_size + 4)
        )
        y = int(image_font_center[1] - font_height / 2)
        draw.text((x, y), text_vertical, fill=color, font=ttfront)

    # 保存图片
    if not OUT_PATH.exists():
        OUT_PATH.mkdir(exist_ok=True, parents=True)

    # 使用时间戳作为文件名
    import time
    timestamp = int(time.time())
    out_path = OUT_PATH / f"fortune_{timestamp}.png"

    img.save(out_path)
    return out_path


# 发送到群

async def send_daily_fortune(websocket, group_id: int, theme: str = "random"):
    """
    向群聊发送每日运势
    :param websocket: WebSocket 连接
    :param group_id: 群号
    :param theme: 主题名称
    """
    import json
    import base64

    try:
        print(f"🎴 正在为群 {group_id} 生成运势卡片...")

        # 生成运势卡片
        img_path = drawing(theme)

        # 读取图片
        with open(img_path, 'rb') as f:
            img_data = base64.b64encode(f.read()).decode('utf-8')

        # 发送图片
        await websocket.send(json.dumps({
            "action": "send_msg",
            "params": {
                "message_type": "group",
                "group_id": group_id,
                "message": [
                    {"type": "image", "data": {"file": f"base64://{img_data}"}}
                ]
            }
        }))

        print(f"✅ 已向群 {group_id} 发送运势卡片")

        # 清理临时文件
        try:
            img_path.unlink()
        except:
            pass

    except Exception as e:
        print(f"⚠️ 向群 {group_id} 发送运势失败: {e}")
        import traceback
        traceback.print_exc()


# 定时任务

def setup_daily_fortune_scheduler(
        websocket,
        target_groups: List[int],
        push_hour: int = 8,
        push_minute: int = 0,
        theme: str = "random"
):
    """
    设置每日运势定时推送

    :param websocket: WebSocket 连接
    :param target_groups: 目标群号列表
    :param push_hour: 推送小时（0-23）
    :param push_minute: 推送分钟（0-59）
    :param theme: 主题名称（"random" 表示随机）
    """
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    import asyncio

    scheduler = AsyncIOScheduler()

    async def daily_fortune_task():
        """每日运势推送任务"""
        print(f"🔮 开始推送每日运势...")

        for group_id in target_groups:
            try:
                await send_daily_fortune(websocket, group_id, theme)
                await asyncio.sleep(3)  # 避免发送过快
            except Exception as e:
                print(f"⚠️ 向群 {group_id} 推送失败: {e}")

        print(f"✅ 每日运势推送完成")

    # 添加定时任务
    scheduler.add_job(
        daily_fortune_task,
        CronTrigger(hour=push_hour, minute=push_minute),
        id='daily_fortune_push',
        replace_existing=True
    )

    scheduler.start()
    print(f"⏰ 每日运势定时推送已启动: 每天 {push_hour:02d}:{push_minute:02d}")

    return scheduler


# 清理临时文件

def cleanup_old_images(days: int = 7):
    """
    清理旧的运势图片
    :param days: 保留最近几天的图片
    """
    import time

    if not OUT_PATH.exists():
        return

    cutoff = time.time() - (days * 86400)

    for file in OUT_PATH.glob("fortune_*.png"):
        try:
            if file.stat().st_mtime < cutoff:
                file.unlink()
                print(f"🗑️ 清理旧图片: {file.name}")
        except:
            pass