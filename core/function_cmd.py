import config
from core.function_image_providers import *

def special_event(event):
    """
    两类命令：
    1) 拉图命令（群聊/私聊均可）：#图 ...   或  /img ...
       -> 返回 {message_type, group_id/user_id, message:[...]}，主循环检测到有 message 就直接发送，不走大模型
    2) 控制台命令（只允许特定用户私聊）：以 config.CMD_PREFIX 开头，例如 /s 群聊 123456
       -> 保持你原有返回结构 {message_type, group_id/user_id}，主循环仍旧交给大模型生成文本
    """
    try:
        msg_list = event.get("message")
        # 先尝试识别“拉图命令”
        if isinstance(msg_list, list) and msg_list and msg_list[0].get("type") == "text":
            cmd_text = (msg_list[0].get("data") or {}).get("text", "").strip()

            # ---- 图片命令：#图 / /img ----
            if cmd_text.startswith("#图") or cmd_text.startswith("/img"):
                # 解析标签
                parts = cmd_text.split()
                tags = parts[1:] if len(parts) > 1 else []

                # 路由：回到消息来源（群 or 私聊）
                route = {"message_type": event.get("message_type")}
                if route["message_type"] == "group":
                    route["group_id"] = event.get("group_id")
                else:
                    route["user_id"] = event.get("user_id")

                # 拉图（R-18 你已说明不是问题，这里默认 True；需要变更可以加判断）
                try:
                    url, src = fetch_acg_one(tags=tags, r18=True)
                except Exception as e:
                    url, src = None, None

                # 组织返回 message 段（OneBot v11 标准）
                if url:
                    route["message"] = [
                        {"type": "text", "data": {"text": f"[{src}] "}},
                        {"type": "image", "data": {"file": url}}
                    ]
                else:
                    route["message"] = [
                        {"type": "text", "data": {"text": "没找到符合标签的图片 :("}}
                    ]
                return route  # 注意：含有 "message" 字段 -> 主循环直接发送

        # ---- 非拉图命令 → 保持你原有的“控制台”命令逻辑 ----
        # 仅允许特定用户在私聊里用控制台命令
        if event.get("message_type") == "group" or event.get("user_id") != config.TARGET_USER_ID:
            return False

        # 下面是你原本的控制台命令解析
        try:
            cmd = event.get("message")[0]["data"]["text"]
            if cmd.startswith(config.CMD_PREFIX):
                parts = cmd.split(" ", 2)

                if len(parts) == 3 and parts[2] in config.ALLOWED_GROUPS:
                    target_type = parts[1]
                    target_id = parts[2]

                    if target_type == "群聊":
                        print(f"💬 正在向群 {target_id} 发送消息")
                        return {"group_id": target_id, "message_type": "group"}

                    elif target_type == "私聊":
                        print(f"💬 正在向用户 {target_id} 发送消息")
                        return {"user_id": target_id, "message_type": "private"}

                print("⚠️ 格式错误或不合法的群聊")
                return None

            else:
                return False

        except Exception as e:
            print(f"❗ 控制台事件处理失败: {e}")
            return None

    except Exception as e:
        print(f"❗ special_event 处理失败: {e}")
        return None
