import asyncio
import json
import time
import traceback
import uuid
from weakref import WeakValueDictionary

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
    is_allowed_group,
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
from src.qqbot.core.function_message import QQMessageParser, event_message, sender_name
from src.qqbot.core.function_tools import TOOLS
from src.qqbot.core.function_render import build_rendered_image_segments, cleanup_rendered_images
from src.qqbot.utils.console import out

CURRENT_LLM = config.LLM[config.CURRENT_COMPLETION]
LLM_NAME = CURRENT_LLM["NAME"]
system_prompt = config.PROMPT[0] + config.PROMPT[config.CURRENT_PROMPT]

memory_pool = LocalDictStore()
memory_manager = MemoryManager(
    timeout=config.HISTORY_TIMEOUT,
    context_window=config.MESSAGE_COUNT  # 只限制首次导入量
)

# 主接收循环按 echo 唤醒对应请求，避免多个协程同时读取 WebSocket。
_pending_actions = {}  # {echo_id: asyncio.Future}

# 图片描述结果按 URL 缓存，限制容量以控制内存和视觉模型调用次数。
_IMAGE_DESCRIPTION_CACHE = {}
_IMAGE_DESCRIPTION_CACHE_MAX_SIZE = 200

# 对话链按模型缓存；后台任务集合保证记忆写入任务持续到完成。
_CHAIN_CACHE = {}
_BACKGROUND_TASKS = set()
_MESSAGE_TASKS = set()
_SESSION_LOCKS = WeakValueDictionary()

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


def _empty_completion():
    return {"text": "", "emoji": None, "rendered_image_ids": []}


async def ai_completion(session_id, user_content):
    """Apply one total deadline to memory lookup, image description and all agent attempts."""
    history = list(memory_manager.get_history(session_id).messages)
    try:
        return await asyncio.wait_for(
            _ai_completion(session_id, user_content, history),
            timeout=config.AGENT_CONFIG["TURN_TIMEOUT"],
        )
    except asyncio.TimeoutError:
        out("⏱️ 本轮总预算耗尽，已取消后续生成，本轮不发送")
        return _empty_completion()


async def _ai_completion(session_id, user_content, history_msgs):
    """输入会话标识和消息内容，返回生成的文本回复。"""
    try:
        user_id = session_id
        prompt_context = memory_manager.get_prompt_context(session_id)

        if not user_content:
            return _empty_completion()

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
            for msg in history_msgs:
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

            async def fetch_image_description(image_url: str) -> str:
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
                            llm.ainvoke(
                                [HumanMessage(content=[
                                    {"type": "text", "text": config.IMAGE_DESCRIPTION_PROMPT},
                                    {"type": "image_url", "image_url": {"url": image_url}}
                                ])]
                            ),
                            timeout=30.0
                        )
                    else:
                        desc_response = await asyncio.wait_for(
                            llm.ainvoke(
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

            # Freeze even failures for this conversation so old model input never
            # changes after new images arrive or the global URL cache is evicted.
            async def get_image_description(image_url):
                frozen = prompt_context.image_descriptions
                if image_url not in frozen:
                    frozen[image_url] = await fetch_image_description(image_url)
                return frozen[image_url]

            described_history = []

            async def describe_parts(parts):
                result = []
                for part in parts:
                    if not isinstance(part, dict):
                        continue
                    if part.get("type") == "text":
                        result.append(part.get("text", ""))
                    elif part.get("type") in ("image_url", "image"):
                        url = (part.get("image_url", {}).get("url", "")
                               if part["type"] == "image_url" else part.get("url", ""))
                        if url:
                            description = await get_image_description(url)
                            result.append(f"[图片内容: {description}]")
                return "".join(result)

            for msg in history_msgs:
                if isinstance(msg, HumanMessage) and isinstance(msg.content, list):
                    text = await describe_parts(msg.content)
                    if text.strip():
                        described_history.append(HumanMessage(content=text, additional_kwargs=msg.additional_kwargs))
                elif isinstance(msg, (HumanMessage, AIMessage)):
                    described_history.append(msg)

            combined_text = await describe_parts(user_content)

            user_content = [{"type": "text", "text": combined_text}]

            # Descriptions belong only to this turn's snapshot. Never pop or
            # rewrite the shared history after awaiting remote image work.
            history_msgs = described_history

        # 依次尝试配置中的候选模型。
        names = [s.strip() for s in str(LLM_NAME).split(",") if s.strip()]

        last_err = None
        max_retries = 2  # 每个模型最多重试 2 次

        for model_name in names:
            retry_count = 0

            while retry_count <= max_retries:
                response_received = False
                rendered_ids = []
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
                    response = await chain.ainvoke(
                        {"input": [input_msg], "long_memory": long_mem,
                         "emoji_options": emoji_options, "history": history_msgs,
                         "prompt_context": prompt_context},
                        run_config={"configurable": {"session_id": session_id}},
                    )
                    response_received = True
                    if isinstance(response, dict):
                        rendered_ids = response.get("rendered_image_ids", [])
                    if (config.AGENT_CONFIG["REVIEW_ENABLED"]
                            and (not isinstance(response, dict)
                                 or response.get("review_approved") is not True)):
                        out("⛔ 回复未通过后台验收，本轮不发送、不写入记忆",
                            response.get("review_status", "unknown") if isinstance(response, dict) else "invalid_result")
                        cleanup_rendered_images(rendered_ids)
                        return _empty_completion()
                    if isinstance(response, dict):
                        content = response.get("output", "")
                        rendered_ids = response.get("rendered_image_ids", [])
                    else:
                        content = response.content if hasattr(response, 'content') else str(response)
                        rendered_ids = []

                    content = lc_message_to_text(content) if not isinstance(content, str) else content
                    content = content.strip() if content else ""
                    out("🤖 AI 原始回复:", content or "（空）")

                    if not content or "Agent stopped due to" in content:
                        cleanup_rendered_images(rendered_ids)
                        return _empty_completion()
                    model_content = response.get("model_content", content) if isinstance(response, dict) else content
                    try:
                        content, emoji_name = parse_emoji_reply(content, emoji_options)
                    except ValueError as error:
                        out("⛔ 回复协议解析失败，本轮不发送", error)
                        cleanup_rendered_images(rendered_ids)
                        return _empty_completion()

                    out("✅ 使用模型：", model_name)

                    return {
                        "text": content,
                        "emoji": emoji_name,
                        "rendered_image_ids": rendered_ids,
                        "memory_turn": {"user_id": user_id, "user_text": user_text},
                        "model_content": model_content,
                    }

                except Exception as e:
                    if response_received:
                        cleanup_rendered_images(rendered_ids)
                        out("⛔ 生成后的处理失败，不重新执行模型和工具", e)
                        return _empty_completion()
                    last_err = e
                    retry_count += 1
                    if retry_count <= max_retries:
                        out("⚠️ 模型调用失败，准备重试", f"{model_name}: {e}")
                        await asyncio.sleep(1)
                        continue
                    else:
                        out("⚠️ 模型调用失败，已达最大重试次数", f"{model_name}: {e}")
                        break
        # 所有模型都失败，返回默认回复
        out("⚠️ 全部候选模型失败", last_err)
        out("⛔ 本轮生成失败，不发送未经处理的兜底回复")
        return _empty_completion()

    except Exception as e:
        out("⚠️ 调用 LLM 发生错误", e)
        out("⛔ 本轮生成失败，不发送未经处理的兜底回复")
        return _empty_completion()


async def send_message(websocket, params, action="send_msg"):
    """Only report success after OneBot acknowledges delivery."""
    if params is None:
        raise ValueError("params is None")
    try:
        result = await send_action_and_wait(websocket, action, params)
        if (isinstance(result, dict) and result.get("status") == "ok"
                and result.get("retcode") == 0):
            return True
        # An ACK timeout is ambiguous: resending could duplicate a message.
        out("⚠️ OneBot 未确认发送成功，不自动重发、不写入回复记忆",
            {"状态": result.get("status"), "返回码": result.get("retcode")} if result else "无回执")
    except Exception as error:
        out("⚠️ 消息发送异常", error)
    return False

async def remember(websocket, event):
    """初始化会话历史并保存当前消息，返回模型输入内容。"""
    try:
        session_id = calc_session_id(event)
        async def message_action(action, params, timeout):
            return await send_action_and_wait(websocket, action, params, timeout=timeout)

        parser = QQMessageParser(
            config.SELF_USER_ID, action=message_action,
            lookup=lambda message_id, seq: memory_manager.get_source_message(session_id, message_id, seq),
        )

        # 首次收到该会话的消息时，从 NapCat 补齐最近上下文。
        if not memory_manager.is_session_initialized(session_id):
            out("🔍 首次记忆，正在拉取历史消息")

            msg_type = event.get("message_type")
            key = "group_id" if msg_type == "group" else "user_id"
            act = "get_group_msg_history" if msg_type == "group" else "get_friend_msg_history"
            current_id = event[key]

            params = {key: current_id, "message_seq": 0, "count": config.MESSAGE_COUNT}
            if msg_type == "group":
                params["parse_mult_msg"] = False
            result = await send_action_and_wait(
                websocket,
                act,
                params,
                timeout=5.0
            )

            if result and result.get("status") == "ok":
                data = result.get("data")
                messages = data.get("messages", []) if isinstance(data, dict) else []
                messages = [msg for msg in messages if isinstance(msg, dict)] if isinstance(messages, list) else []
                # The latest-history response can already contain this event
                # and even later queued events. Keep only its predecessors.
                message_id = event.get("message_id")
                found_current = False
                if message_id is not None:
                    for index, previous in enumerate(messages):
                        if str(previous.get("message_id")) == str(message_id):
                            messages = messages[:index]
                            found_current = True
                            break
                if not found_current:
                    # A busy group can push this event out of the returned
                    # history window. Never import messages newer than it.
                    event_time = event.get("time")
                    messages = [previous for previous in messages
                                if isinstance(event_time, (int, float))
                                and isinstance(previous.get("time"), (int, float))
                                and previous["time"] < event_time]
                history_msgs = messages[-config.MESSAGE_COUNT:] if messages else []
                await memory_manager.initialize_with_history(
                    session_id, history_msgs, event_context=event)
            else:
                # Once live events start accumulating, a later bootstrap must
                # not overwrite that conversation and its stable model prefix.
                out("⚠️ 初始历史拉取失败，从本条消息开始保留会话")
                await memory_manager.initialize_with_history(session_id, [])

        message = event_message(event)
        nickname = sender_name(event)

        msgs = await process_single_message(message, nickname, CURRENT_LLM, parser=parser, event=event)

        # 统一保留文本与图片分段，供后续模型调用使用。
        all_user_content = []

        for msg in msgs:
            role = msg.get("role")
            content = msg.get("content", [])

            if role == "user" and content:
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

        # One QQ event is one history message, including all text/image segments.
        if all_user_content:
            memory_manager.add_user_message(session_id, all_user_content)
        memory_manager.cache_message(session_id, event)
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
            rendered_ids = completion.get("rendered_image_ids", [])
        else:
            content = completion
            emoji_name = None
            rendered_ids = []

        if not content and not rendered_ids:
            return

        message_segments = []
        if content:
            message_segments.append({"type": "text", "data": {"text": content}})

        images = await build_rendered_image_segments(rendered_ids)
        if len(images) != len(rendered_ids):
            out("⛔ 渲染附件不完整，本轮不发送成功文案、不写入回复记忆")
            return
        message_segments.extend(images)
        if not message_segments:
            return
        if not await send_message(websocket, build_params("segments", event, message_segments)):
            return

        if event.get("_proactive_reply"):
            memory_manager.mark_proactive_reply(session_id)
        memory_manager.add_ai_message(
            session_id, content,
            model_content=completion.get("model_content", content) if isinstance(completion, dict) else content,
        )
        out("💾 AI 回复已加入上下文:", content[:80])
        memory_turn = completion.get("memory_turn") if isinstance(completion, dict) else None
        if memory_turn and content:
            def add_long_memory():
                try:
                    memory_pool.add_turn(assistant_text=content, **memory_turn)
                except Exception as error:
                    out("⚠️ Mem0 写入失败", error)
            task = asyncio.create_task(asyncio.to_thread(add_long_memory))
            _BACKGROUND_TASKS.add(task)
            task.add_done_callback(_BACKGROUND_TASKS.discard)

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

        fortune_scheduler = setup_daily_fortune_scheduler(
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

                    # ACK waits run in tasks so this sole reader stays available.

                    if event.get("post_type") == "notice" and event.get("sub_type") == "poke" and event.get(
                            "target_id") == config.SELF_USER_ID:
                        _start_message_task(send_message(ws, build_params_text_only(event, ran_rep_text_only())))
                        continue

                    if event.get("post_type") != "message":
                        continue

                    # 消息处理可能包含远程调用，交由独立任务执行。
                    _start_message_task(_process_message_concurrent(ws, event))

                except json.JSONDecodeError:
                    out("⚠️ 收到非 JSON 格式消息")
                except Exception as e:
                    out("⚠️ 分发消息失败", e)

        finally:
            out("🔌 连接断开，清理悬空 action 请求")
            fortune_scheduler.shutdown(wait=False)
            for fut in list(_pending_actions.values()):
                if not fut.done():
                    fut.cancel()
            _pending_actions.clear()
            tasks = list(_MESSAGE_TASKS)
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)


def _start_message_task(coroutine):
    task = asyncio.create_task(coroutine)
    _MESSAGE_TASKS.add(task)
    task.add_done_callback(_MESSAGE_TASKS.discard)
    return task


async def _process_message_concurrent(ws, event):
    """Serialize each conversation; independent groups may still run concurrently."""
    try:
        session_id = calc_session_id(event)
        lock = _SESSION_LOCKS.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            _SESSION_LOCKS[session_id] = lock
        async with lock:
            await _process_message(ws, event)
    except Exception as error:
        out("⚠️ 会话处理失败", error)


async def _process_message(ws, event):
    """Record and handle one event while holding its conversation lock."""
    try:
        sender = event.get("sender") if isinstance(event.get("sender"), dict) else {}
        sender_id = sender.get("user_id", event.get("user_id"))
        if str(sender_id) == str(config.SELF_USER_ID):
            memory_manager.cache_message(calc_session_id(event), event)
            return
        if not is_allowed_group(event):
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
