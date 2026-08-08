import asyncio
import json
import time
import traceback
import uuid

import websockets
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.qqbot.config import config
from src.qqbot.config.config import FORTUNE_GROUPS
from src.qqbot.core.function import (
    build_params,
    build_emoji_params,
    get_available_emojis,
    build_params_text_only,
    process_single_message,
    ran_rep_text_only,
    rep,
)
from src.qqbot.core.function_completion import (
    create_chat_llm,
    create_agent_chain_with_memory,
    get_long_memory_text,
    lc_message_to_text,
    parse_emoji_reply,
)
from src.qqbot.core.function_fortune import setup_daily_fortune_scheduler
from src.qqbot.core.function_long_turn_memory import LocalDictStore
from src.qqbot.core.function_session_memory import MemoryManager, calc_session_id
from src.qqbot.core.function_tools import TOOLS
from src.qqbot.utils.console import out

CURRENT_LLM = config.LLM[config.CURRENT_COMPLETION]
LLM_NAME = CURRENT_LLM["NAME"]
system_prompt = config.PROMPT[0] + config.PROMPT[config.CURRENT_PROMPT]

memory_pool = LocalDictStore()
memory_manager = MemoryManager(
    timeout=config.HISTORY_TIMEOUT,
    context_window=30  # 与 MESSAGE_COUNT 保持一致
)

# 主接收循环按 echo 唤醒对应请求，避免多个协程同时读取 WebSocket。
_pending_actions = {}  # {echo_id: asyncio.Future}

# 图片描述结果按 URL 缓存，限制容量以控制内存和视觉模型调用次数。
_IMAGE_DESCRIPTION_CACHE = {}
_IMAGE_DESCRIPTION_CACHE_MAX_SIZE = 200

# 对话链按模型缓存；后台任务集合保证记忆写入任务持续到完成。
_CHAIN_CACHE = {}
_BACKGROUND_TASKS = set()

def _clear_chain_cache():
    """清空对话链缓存。"""
    global _CHAIN_CACHE
    _CHAIN_CACHE = {}


async def send_action_and_wait(websocket, action, params, timeout=10.0):
    """发送 action，并按 echo 等待对应响应。"""
    echo_id = f"action_{uuid.uuid4().hex}"

    future = asyncio.Future()
    _pending_actions[echo_id] = future

    try:
        payload = {
            "action": action,
            "params": params,
            "echo": echo_id
        }
        await websocket.send(json.dumps(payload))

        # 等待响应，带超时
        result = await asyncio.wait_for(future, timeout=timeout)
        return result
    except asyncio.TimeoutError:
        out("⏱️ Action 超时", action)
        return None
    finally:
        _pending_actions.pop(echo_id, None)


async def ai_completion(session_id, user_content):
    """输入会话标识和消息内容，返回生成的文本回复。"""
    try:
        user_id = session_id.split(":", 1)[-1] if ":" in session_id else session_id

        if not user_content:
            return "嗯"

        # Mem0 是同步客户端，放入工作线程以免阻塞 WebSocket 事件循环。
        user_text = "".join([p.get("text", "") for p in user_content if isinstance(p, dict) and p.get("type") == "text"])
        out("📚 开始查询长期记忆", "")
        try:
            long_mem = await asyncio.wait_for(
                asyncio.to_thread(get_long_memory_text, memory_pool, user_id, user_text),
                timeout=10.0
            )
            out("✅ 长期记忆查询完成", "")
        except asyncio.TimeoutError:
            out("⏱️ 长期记忆查询超时，跳过")
            long_mem = "（无）"
        except Exception as e:
            out("⚠️ 长期记忆查询失败", e)
            long_mem = "（无）"

        out("🏁 [ai_completion] 调用 chain, session:", session_id)
        out("📝 [ai_completion] 用户输入:", str(user_content)[:100])

        # 工具链只接收文本，因此图片消息需要先转换为描述。
        has_image = any(isinstance(p, dict) and p.get("type") in ["image_url", "image"] for p in user_content)

        if not has_image:
            history = memory_manager.get_history(session_id)
            for msg in history.messages:
                if hasattr(msg, 'content') and isinstance(msg.content, list):
                    if any(isinstance(p, dict) and p.get("type") == "image_url" for p in msg.content):
                        has_image = True
                        out("🖼️ 检测到历史消息中有图片", "生成图片描述")
                        break

        if has_image:
            names = [s.strip() for s in str(LLM_NAME).split(",") if s.strip()]
            temp_config = CURRENT_LLM.copy()
            temp_config["NAME"] = names[0]
            llm = create_chat_llm(temp_config)

            history = memory_manager.get_history(session_id)

            async def get_image_description(image_url: str) -> str:
                if image_url in _IMAGE_DESCRIPTION_CACHE:
                    out("💾 使用缓存的图片描述", image_url[:80])
                    return _IMAGE_DESCRIPTION_CACHE[image_url]

                if len(_IMAGE_DESCRIPTION_CACHE) >= _IMAGE_DESCRIPTION_CACHE_MAX_SIZE:
                    keys_to_remove = list(_IMAGE_DESCRIPTION_CACHE.keys())[:_IMAGE_DESCRIPTION_CACHE_MAX_SIZE // 2]
                    for key in keys_to_remove:
                        del _IMAGE_DESCRIPTION_CACHE[key]
                    out("🧹 图片描述缓存已清理", f"删除 {len(keys_to_remove)} 条旧记录")

                try:
                    if CURRENT_LLM.get("USE_RESPONSES_API"):
                        desc_response = await asyncio.wait_for(
                            asyncio.to_thread(
                                llm.invoke,
                                [HumanMessage(content=[
                                    {"type": "text", "text": config.IMAGE_DESCRIPTION_PROMPT},
                                    {"type": "image_url", "image_url": {"url": image_url}}
                                ])]
                            ),
                            timeout=30.0
                        )
                    else:
                        desc_response = await asyncio.wait_for(
                            asyncio.to_thread(
                                llm.invoke,
                                [
                                    SystemMessage(content=config.IMAGE_DESCRIPTION_PROMPT),
                                    HumanMessage(content=[{"type": "image_url", "image_url": {"url": image_url}}])
                                ]
                            ),
                            timeout=30.0
                        )
                    description = lc_message_to_text(desc_response).strip()

                    _IMAGE_DESCRIPTION_CACHE[image_url] = description
                    out("🖼️ 新图片描述生成", description[:100])

                    return description

                except asyncio.TimeoutError:
                    return "[图片识别超时]"
                except Exception as e:
                    out("⚠️ 图片描述失败", str(e))
                    return "[图片识别失败]"

            # 仅识别最近五张图片，避免历史图片无限增加请求与上下文长度。
            described_history = []
            MAX_IMAGES = 5

            _all_img_urls = []
            for msg in history.messages:
                if isinstance(msg, HumanMessage) and isinstance(msg.content, list):
                    for part in msg.content:
                        if isinstance(part, dict) and part.get("type") == "image_url":
                            u = part.get("image_url", {}).get("url", "")
                            if u:
                                _all_img_urls.append(u)
            for part in user_content:
                if isinstance(part, dict) and part.get("type") in ("image_url", "image"):
                    u = part.get("image_url", {}).get("url", "") if part.get("type") == "image_url" else part.get("url", "")
                    if u:
                        _all_img_urls.append(u)

            _seen = []
            for u in _all_img_urls:
                if u in _seen:
                    _seen.remove(u)
                _seen.append(u)
            keep_urls = set(_seen[-MAX_IMAGES:])

            for msg in history.messages:
                if isinstance(msg, HumanMessage) and isinstance(msg.content, list):
                    text_parts = []
                    image_descs = []

                    for part in msg.content:
                        if isinstance(part, dict):
                            if part.get("type") == "text":
                                text_parts.append(part.get("text", ""))
                            elif part.get("type") == "image_url":
                                img_url = part.get("image_url", {}).get("url", "")
                                if img_url:
                                    if img_url in keep_urls:
                                        desc = await get_image_description(img_url)
                                        image_descs.append(desc)
                                    else:
                                        image_descs.append("[过期图片]")

                    combined_text = "".join(text_parts)
                    if image_descs:
                        combined_text += " [图片内容: " + "; ".join(image_descs) + "]"

                    if combined_text.strip():
                        described_history.append(HumanMessage(content=combined_text))
                elif isinstance(msg, AIMessage):
                    described_history.append(msg)
                elif isinstance(msg, HumanMessage):
                    described_history.append(msg)

            text_parts = []
            image_descs = []

            for part in user_content:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        text_parts.append(part.get("text", ""))
                    elif part.get("type") in ["image_url", "image"]:
                        img_url = part.get("image_url", {}).get("url", "") if part.get("type") == "image_url" else part.get("url", "")
                        if img_url:
                            if img_url in keep_urls:
                                desc = await get_image_description(img_url)
                                image_descs.append(desc)
                            else:
                                image_descs.append("[过期图片]")

            combined_text = "".join(text_parts)
            if image_descs:
                combined_text += " [图片内容: " + "; ".join(image_descs) + "]"

            user_content = [{"type": "text", "text": combined_text}]

            temp_session_id = f"{session_id}_temp_{uuid.uuid4().hex[:8]}"
            temp_session = memory_manager.get_or_create_session(temp_session_id)
            temp_session.history.clear()
            for msg in described_history:
                temp_session.history.add_message(msg)

            agent_session_id = temp_session_id
        else:
            agent_session_id = session_id

        # 依次尝试配置中的候选模型。
        names = [s.strip() for s in str(LLM_NAME).split(",") if s.strip()]

        last_err = None
        max_retries = 2  # 每个模型最多重试 2 次

        try:
            for model_name in names:
                retry_count = 0

                while retry_count <= max_retries:
                    try:
                        temp_config = CURRENT_LLM.copy()
                        temp_config["NAME"] = model_name

                        if model_name not in _CHAIN_CACHE:
                            _CHAIN_CACHE[model_name] = create_agent_chain_with_memory(
                                memory_manager=memory_manager,
                                long_memory_pool=memory_pool,
                                system_prompt=system_prompt,
                                llm_config=temp_config,
                                tools=TOOLS
                            )
                        chain = _CHAIN_CACHE[model_name]

                        input_msg = HumanMessage(content=user_content)

                        if retry_count > 0:
                            out("🔄 模型重试", f"{model_name}，第 {retry_count + 1} 次")

                        emoji_options = get_available_emojis()
                        try:
                            response = await asyncio.wait_for(
                                asyncio.to_thread(
                                    chain.invoke,
                                    {
                                        "input": [input_msg],
                                        "long_memory": long_mem,
                                        "emoji_options": emoji_options,
                                    },
                                    run_config={"configurable": {"session_id": agent_session_id}}
                                ),
                                timeout=60.0
                            )
                        except asyncio.TimeoutError as timeout_err:
                            last_err = timeout_err
                            retry_count += 1
                            if retry_count <= max_retries:
                                out("⏱️ 模型超时，准备重试", f"{model_name}，第 {retry_count} 次")
                                await asyncio.sleep(1)  # 短暂延迟后重试
                                continue
                            else:
                                out("⏱️ 模型超时，尝试下一个模型", model_name)
                                break

                        if isinstance(response, dict):
                            content = response.get("output", "")
                        else:
                            content = response.content if hasattr(response, 'content') else str(response)

                        content = lc_message_to_text(content) if not isinstance(content, str) else content
                        content = content.strip() if content else ""
                        out("🤖 AI 原始回复:", content or "（空）")

                        if not content or "Agent stopped due to" in content:
                            content = "嗯"

                        content, emoji_name = parse_emoji_reply(content, emoji_options)

                        out("短期记忆：", memory_manager.get_or_create_session(session_id).history)
                        out("✅ 使用模型：", model_name)

                        def add_long_memory():
                            try:
                                memory_pool.add_turn(
                                    user_id=user_id,
                                    user_text=user_text,
                                    assistant_text=content
                                )
                            except Exception as e:
                                out("⚠️ Mem0 写入失败", e)

                        # 记忆写入不阻塞回复；保留任务引用以便其执行完成。
                        task = asyncio.create_task(asyncio.to_thread(add_long_memory))
                        _BACKGROUND_TASKS.add(task)
                        task.add_done_callback(_BACKGROUND_TASKS.discard)

                        return {"text": content, "emoji": emoji_name}

                    except Exception as e:
                        last_err = e
                        retry_count += 1
                        if retry_count <= max_retries:
                            out("⚠️ 模型调用失败，准备重试", f"{model_name}: {e}")
                            await asyncio.sleep(1)
                            continue
                        else:
                            out("⚠️ 模型调用失败，已达最大重试次数", f"{model_name}: {e}")
                            break
        finally:
            if has_image and agent_session_id != session_id:
                try:
                    if agent_session_id in memory_manager._sessions:
                        del memory_manager._sessions[agent_session_id]
                except Exception as e:
                    out("⚠️ 清理临时会话失败", e)

        # 所有模型都失败，返回默认回复
        out("⚠️ 全部候选模型失败", last_err)
        out("💬 返回默认回复")
        return "嗯"

    except Exception as e:
        out("⚠️ 调用 LLM 发生错误", e)
        out("💬 返回默认回复")
        return "嗯"


async def send_message(websocket, params, action="send_msg", retry_count=3):
    """调用 OneBot action 发送消息，并在连接异常时重试。"""
    if params is None:
        raise ValueError("params is None")

    for attempt in range(retry_count):
        try:
            await websocket.send(json.dumps({
                "action": action,
                "params": params
            }))
            if attempt > 0:
                out("✅ 消息重试成功", f"第 {attempt + 1} 次")
            return True

        except (websockets.exceptions.ConnectionClosed, websockets.exceptions.WebSocketException) as e:
            out("⚠️ WebSocket 发送错误", f"第 {attempt + 1}/{retry_count} 次: {e}")
            if attempt < retry_count - 1:
                await asyncio.sleep(1)
            else:
                out("❌ 消息发送失败，已达到最大重试次数")
                return False

        except Exception as e:
            out("⚠️ 消息发送异常", e)
            return False

    return False

async def remember(websocket, event):
    """初始化会话历史并保存当前消息，返回模型输入内容。"""
    try:
        session_id = calc_session_id(event)

        # 首次收到该会话的消息时，从 NapCat 补齐最近上下文。
        if not memory_manager.is_session_initialized(session_id):
            out("🔍 首次记忆，正在拉取历史消息")

            msg_type = event.get("message_type")
            key = "group_id" if msg_type == "group" else "user_id"
            act = "get_group_msg_history" if msg_type == "group" else "get_friend_msg_history"
            current_id = event[key]

            result = await send_action_and_wait(
                websocket,
                act,
                {key: current_id, "message_seq": 0},
                timeout=5.0
            )

            if result and result.get("status") == "ok":
                messages = result.get("data", {}).get("messages", [])
                history_msgs = messages[-config.MESSAGE_COUNT:] if messages else []
                if history_msgs:
                    await memory_manager.initialize_with_history(session_id, history_msgs)

        message = event.get("message")
        nickname = event.get("sender").get("nickname")

        msgs = await process_single_message(message, nickname, CURRENT_LLM)

        # 统一保留文本与图片分段，供后续模型调用使用。
        all_user_content = []

        for msg in msgs:
            role = msg.get("role")
            content = msg.get("content", [])

            if role == "user" and content:
                memory_manager.add_user_message(session_id, content)

                if isinstance(content, list):
                    all_user_content.extend(content)
                else:
                    all_user_content.append(content)

                text_parts = []
                for part in content:
                    if isinstance(part, dict):
                        if part.get("type") == "text":
                            text_parts.append(part.get("text", ""))
                        elif part.get("type") == "image_url":
                            text_parts.append("[图片]")

                text = "".join(text_parts).strip()
                if text:
                    out("💾 新用户消息:", text[:80])

        return all_user_content if all_user_content else None

    except Exception as e:
        out("⚠️ 记录会话消息失败", e)
        return None

async def handle_message(websocket, event, user_content):
    """为当前事件生成并发送回复，然后更新短期记忆。"""
    try:
        session_id = calc_session_id(event)

        msg_type = event.get("message_type")
        out("⏳ 当前会话:", session_id)

        completion = await ai_completion(session_id, user_content)
        if isinstance(completion, dict):
            content = completion.get("text", "")
            emoji_name = completion.get("emoji")
        else:
            content = completion
            emoji_name = None

        if not content:
            return

        await send_message(websocket, build_params("text", event, content))

        memory_manager.add_ai_message(session_id, content)
        out("💾 AI 回复已加入上下文:", content[:80])

        if emoji_name:
            emoji_params = await build_emoji_params(event, emoji_name)
            if emoji_params:
                await send_message(websocket, emoji_params)

        out("✅ 已回复消息", f"{msg_type}: {content}")

    except Exception as e:
        out("⚠️ 处理回复失败", e)


async def qq_bot():
    """建立 NapCat WebSocket 连接并分发事件。"""
    async with websockets.connect(
        config.WEBSOCKET_URI,
        ping_interval=20,  # 每 20 秒发送一次 ping
        ping_timeout=60    # ping 超时时间 60 秒（足够 AI 推理完成）
    ) as ws:
        out("✅ 已连接 WebSocket 服务器")

        setup_daily_fortune_scheduler(
            websocket=ws,
            target_groups=FORTUNE_GROUPS,
            push_hour=8,
            push_minute=0,
            theme="random"
        )

        try:
            async for message in ws:
                try:
                    event = json.loads(message)

                    if "echo" in event:
                        echo_id = event["echo"]
                        if echo_id in _pending_actions:
                            future = _pending_actions[echo_id]
                            if not future.done():
                                future.set_result(event)
                        continue

                    if event.get("post_type") == "notice" and event.get("sub_type") == "poke" and event.get(
                            "target_id") == config.SELF_USER_ID:
                        await send_message(ws, build_params_text_only(event, ran_rep_text_only()))
                        continue

                    if event.get("post_type") != "message":
                        continue

                    # 消息处理可能包含远程调用，交由独立任务执行。
                    asyncio.create_task(_process_message_concurrent(ws, event))

                except json.JSONDecodeError:
                    out("⚠️ 收到非 JSON 格式消息")
                except Exception as e:
                    out("⚠️ 分发消息失败", e)

        finally:
            out("🔌 连接断开，清理悬空 action 请求")
            for fut in list(_pending_actions.values()):
                if not fut.done():
                    fut.cancel()
            _pending_actions.clear()


async def _process_message_concurrent(ws, event):
    """处理单条消息，并在需要时发送回复。"""
    try:
        sender = event.get("sender") or {}
        sender_id = sender.get("user_id", event.get("user_id"))
        if str(sender_id) == str(config.SELF_USER_ID):
            return

        user_content = await remember(ws, event)

        if not user_content:
            return

        should_reply = await asyncio.to_thread(rep, event, memory_manager)

        if should_reply:
            await handle_message(ws, event, user_content)

    except Exception as e:
        out("⚠️ 并发处理消息失败", e)
        out("并发处理错误详情", traceback.format_exc())



if __name__ == "__main__":
    while True:
        try:
            asyncio.get_event_loop().run_until_complete(qq_bot())

        except (websockets.ConnectionClosed, OSError, ConnectionRefusedError, TimeoutError, websockets.InvalidURI,
                websockets.InvalidHandshake, websockets.WebSocketException):

            out("⏱️ 连接断开，尝试重连")
            time.sleep(3)
            continue

        except KeyboardInterrupt:
            out("🚫 程序已终止")
            break
