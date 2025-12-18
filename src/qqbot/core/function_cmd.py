from src.qqbot.config import config
from src.qqbot.core.function_image_providers import fetch_acg_one
from src.qqbot.utils.image_uploader import get_image_url_or_fallback

def _extract_cmd_text_from_event(msg_list, prefix="/s"):
    """
    从所有 text 段拼接后的文本里，找到第一次出现 prefix 的位置，并截断返回
    例："...(系统提示)... /s img gawr_gura" -> "/s img gawr_gura"
    """
    if not isinstance(msg_list, list):
        return None

    # 拼所有 text 段（忽略 at/image 等）
    texts = []
    for seg in msg_list:
        if seg.get("type") == "text":
            texts.append((seg.get("data") or {}).get("text", ""))

    full = " ".join(texts).strip()
    if not full:
        return None

    idx = full.find(prefix)
    if idx == -1:
        return None

    # 从第一个 /s 开始截断
    cmd_text = full[idx:].strip()
    return cmd_text or None

async def special_event(event):
    """
    仅 /s 开头被当作命令，其他一律当普通消息
    /s img <标签...> [r18]       或   /s 图片 <标签...> [r18]
        -> 直接在这里拉图并返回 {message_type, group_id/user_id, message:[...]}（不走大模型）
    /s 群聊 <ID>   /s 私聊 <ID>
        -> 控制台路由命令（仅限 TARGET_USER_ID 私聊可用）
           - 合法：返回 {message_type, group_id/user_id}（无 message）→ 主循环走大模型
           - 非法：返回带错误提示的 message（不走大模型）
    其它 /s 子命令：
        -> 返回错误提示（不走大模型）
    """
    try:
        msg_list = event.get("message")

        cmd_text = _extract_cmd_text_from_event(msg_list, prefix=config.CMD_PREFIX)
        # 仅 /s 前缀视为命令；否则直接返回 False
        if not cmd_text:
            return False

        # 统一 route（回到消息来源会话）
        route = {"message_type": event.get("message_type")}
        if route["message_type"] == "group":
            route["group_id"] = event.get("group_id")
            route["message"] = [{"type": "text", "data": {"text": "⚠️ 错了喵，怕了喵，不搞了喵"}}]
            return route
        else:
            route["user_id"] = event.get("user_id")

        parts = cmd_text.split()
        if len(parts) < 2:
            route["message"] = [{"type":"text","data":{"text":"⚠️ 用法：/s img <标签...> [r18] ｜ /s 群聊|私聊 <ID>"}}]
            return route

        subcmd = parts[1]

        # ---------- 取图子命令 ----------
        if subcmd in ("img", "图片"):
            # 解析标签与 r18 标志（默认 False）
            raw = parts[2:] if len(parts) > 2 else []
            r18 = False
            tags = []
            for t in raw:
                tl = t.lower()
                if tl in ("r18", "--r18", "-r18", "r18=1", "r18:true"):
                    r18 = True
                elif tl in ("r18=0", "r18:false", "no-r18"):
                    r18 = False
                else:
                    tags.append(t)

            try:
                url, src = fetch_acg_one(tags=tags, r18=r18)  # 默认非 r18；带 r18 才开启
            except Exception as e:
                url, src = None, None

            if url:
                # 上传到Worker或fallback到base64
                final_url = await get_image_url_or_fallback(url)

                route["message"] = [
                    {"type":"text","data":{"text": f"[{src}] "}},
                    {"type":"image","data":{"file": final_url}}
                ]
            else:
                route["message"] = [{"type":"text","data":{"text":"没找到符合标签的图片 :("}}]

            # 输出预览
            try:
                preview = ""
                if isinstance(route["message"], list) and route["message"]:
                    first = route["message"][0]
                    if first.get("type") == "text":
                        preview = (first.get("data") or {}).get("text", "")
                print("----------\n图片请求结果\n" + preview + "\n----------")
            except Exception:
                pass

            return route  # 含 message：主循环直接发送，跳过大模型

        # ---------- 控制台路由子命令 ----------
        if subcmd in ("群聊", "私聊"):
            # 仅限私聊 + 指定用户
            if event.get("message_type") == "group":
                route["message"] = [{"type":"text","data":{"text":"⚠️ 控制台命令仅限私聊使用"}}]
                return route
            if event.get("user_id") != config.TARGET_USER_ID:
                route["message"] = [{"type":"text","data":{"text":"⚠️ 无权使用控制台命令"}}]
                return route

            if len(parts) != 3 or parts[2] not in config.ALLOWED_GROUPS:
                route["message"] = [{"type":"text","data":{"text":"⚠️ 用法：/s 群聊|私聊 <ID>（需在白名单）"}}]
                return route

            target_type, target_id = subcmd, parts[2]
            if target_type == "群聊":
                print(f"💬 正在向群 {target_id} 发送消息")
                return {"message_type": "group", "group_id": target_id}
            else:
                print(f"💬 正在向用户 {target_id} 发送消息")
                return {"message_type": "private", "user_id": target_id}

        # ---------- 未知子命令 ----------
        route["message"] = [{"type":"text","data":{"text":"⚠️ 未知子命令。可用：img/图片、群聊、私聊"}}]
        return route

    except Exception as e:
        print(f"❗ special_event 处理失败: {e}")
        return None
