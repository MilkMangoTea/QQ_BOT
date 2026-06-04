import asyncio
import websockets
import json
import time
from src.qqbot.config import config
from src.qqbot.config.config import FORTUNE_GROUPS
from src.qqbot.core.function import (
    process_single_message,
    get_nearby_message,
    special_event,
    rep,
    build_params_text_only,
    ran_rep_text_only,
    build_params,
    ran_emoji,
    ran_emoji_content,
    get_long_memory_text,
    MemoryManager,
    out
)
from src.qqbot.core.function_completion import create_agent_chain_with_memory, lc_message_to_text
from src.qqbot.core.function_fortune import setup_daily_fortune_scheduler
from src.qqbot.core.function_long_turn_memory import LocalDictStore
from src.qqbot.core.function_session_memory import calc_session_id
from src.qqbot.core.function_tools import TOOLS

CURRENT_LLM = config.LLM[config.CURRENT_COMPLETION]
LLM_NAME = CURRENT_LLM["NAME"]
system_prompt = config.PROMPT[0] + config.PROMPT[config.CURRENT_PROMPT]

memory_pool = LocalDictStore()
memory_manager = MemoryManager(
    timeout=config.HISTORY_TIMEOUT,
    context_window=30  # 与 MESSAGE_COUNT 保持一致
)

# 图片描述缓存：{image_url: description}，限制大小防止内存泄漏
_IMAGE_DESCRIPTION_CACHE = {}
_IMAGE_DESCRIPTION_CACHE_MAX_SIZE = 200  # 最多缓存 200 张图片描述

# 缓存 chain，避免每次都创建新实例
_CHAIN_CACHE = {}

def _clear_chain_cache():
    """清空 chain 缓存"""
    global _CHAIN_CACHE
    _CHAIN_CACHE = {}

# 大模型请求器(注意message不能为空!)
async def ai_completion(session_id):
    try:
        from langchain_core.messages import HumanMessage

        user_id = session_id.split(":", 1)[-1] if ":" in session_id else session_id

        # 从历史记忆中获取最后一条用户消息
        history = memory_manager.get_history(session_id)
        if not history.messages:
            return "嗯"

        # 找到最后一条用户消息
        last_user_msg = None
        for msg in reversed(history.messages):
            if isinstance(msg, HumanMessage):
                last_user_msg = msg
                break

        if not last_user_msg:
            return "嗯"

        # 提取当前消息内容
        user_content = last_user_msg.content if isinstance(last_user_msg.content, list) else [{"type": "text", "text": str(last_user_msg.content)}]

        # 获取长期记忆（放到线程池执行，避免阻塞）
        user_text = "".join([p.get("text", "") for p in user_content if isinstance(p, dict) and p.get("type") == "text"])
        out("📚 开始查询长期记忆", "")
        try:
            long_mem = await asyncio.wait_for(
                asyncio.to_thread(get_long_memory_text, memory_pool, user_id, user_text),
                timeout=10.0
            )
            out("✅ 长期记忆查询完成", "")
        except asyncio.TimeoutError:
            print("⏱️ 长期记忆查询超时，跳过")
            long_mem = "（无）"
        except Exception as e:
            print(f"⚠️ 长期记忆查询失败: {e}")
            long_mem = "（无）"

        out("🏁 [ai_completion] 调用 chain, session:", session_id)
        out("📝 [ai_completion] 用户输入:", str(user_content)[:100])

        # 检查当前输入是否有图片
        has_image = any(isinstance(p, dict) and p.get("type") in ["image_url", "image"] for p in user_content)

        # 检查最近历史中是否有图片（扩大到整个上下文窗口）
        if not has_image:
            history = memory_manager.get_history(session_id)
            for msg in history.messages:
                if hasattr(msg, 'content') and isinstance(msg.content, list):
                    if any(isinstance(p, dict) and p.get("type") == "image_url" for p in msg.content):
                        has_image = True
                        out("🖼️ 检测到历史消息中有图片", "生成图片描述")
                        break

        # 如果有图片，先生成描述（使用缓存避免重复识别）
        if has_image:
            from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
            from src.qqbot.core.function_completion import create_chat_llm

            # 使用第一个模型生成图片描述
            names = [s.strip() for s in str(LLM_NAME).split(",") if s.strip()]
            temp_config = CURRENT_LLM.copy()
            temp_config["NAME"] = names[0]
            llm = create_chat_llm(temp_config)

            history = memory_manager.get_history(session_id)

            # 辅助函数：从图片URL获取描述（带缓存）
            async def get_image_description(image_url: str) -> str:
                if image_url in _IMAGE_DESCRIPTION_CACHE:
                    out("💾 使用缓存的图片描述", image_url[:80])
                    return _IMAGE_DESCRIPTION_CACHE[image_url]

                # 检查缓存大小，超过限制时清理最旧的 50%
                if len(_IMAGE_DESCRIPTION_CACHE) >= _IMAGE_DESCRIPTION_CACHE_MAX_SIZE:
                    keys_to_remove = list(_IMAGE_DESCRIPTION_CACHE.keys())[:_IMAGE_DESCRIPTION_CACHE_MAX_SIZE // 2]
                    for key in keys_to_remove:
                        del _IMAGE_DESCRIPTION_CACHE[key]
                    out("🧹 图片描述缓存已清理", f"删除 {len(keys_to_remove)} 条旧记录")

                try:
                    # 添加超时保护（30秒）
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

                    # 缓存结果
                    _IMAGE_DESCRIPTION_CACHE[image_url] = description
                    out("🖼️ 新图片描述生成", description[:100])

                    return description

                except asyncio.TimeoutError:
                    return "[图片识别超时]"
                except Exception as e:
                    out("⚠️ 图片描述失败", str(e))
                    return "[图片识别失败]"

            # 收集所有包含图片的消息并生成描述（创建新列表，不修改原 memory）
            # 限制：只处理最近的5张图片，其余显示为 [过期图片]
            described_history = []
            image_count = 0
            MAX_IMAGES = 5

            for msg in history.messages:
                if isinstance(msg, HumanMessage) and isinstance(msg.content, list):
                    # 提取文本和图片
                    text_parts = []
                    image_descs = []

                    for part in msg.content:
                        if isinstance(part, dict):
                            if part.get("type") == "text":
                                text_parts.append(part.get("text", ""))
                            elif part.get("type") == "image_url":
                                img_url = part.get("image_url", {}).get("url", "")
                                if img_url:
                                    if image_count < MAX_IMAGES:
                                        desc = await get_image_description(img_url)
                                        image_descs.append(desc)
                                        image_count += 1
                                    else:
                                        image_descs.append("[过期图片]")

                    # 合并文本和图片描述
                    combined_text = "".join(text_parts)
                    if image_descs:
                        combined_text += " [图片内容: " + "; ".join(image_descs) + "]"

                    if combined_text.strip():
                        described_history.append(HumanMessage(content=combined_text))
                elif isinstance(msg, AIMessage):
                    # AI 消息直接复制
                    described_history.append(msg)
                elif isinstance(msg, HumanMessage):
                    # 纯文本用户消息
                    described_history.append(msg)

            # 处理当前输入中的图片（继续使用相同的计数器）
            text_parts = []
            image_descs = []

            for part in user_content:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        text_parts.append(part.get("text", ""))
                    elif part.get("type") in ["image_url", "image"]:
                        img_url = part.get("image_url", {}).get("url", "") if part.get("type") == "image_url" else part.get("url", "")
                        if img_url:
                            if image_count < MAX_IMAGES:
                                desc = await get_image_description(img_url)
                                image_descs.append(desc)
                                image_count += 1
                            else:
                                image_descs.append("[过期图片]")

            # 更新 user_content 为纯文本
            combined_text = "".join(text_parts)
            if image_descs:
                combined_text += " [图片内容: " + "; ".join(image_descs) + "]"

            user_content = [{"type": "text", "text": combined_text}]

            # 临时创建一个包含描述的 session，用于 Agent 推理
            # 原始 memory 保持不变
            temp_session_id = session_id + "_temp_described"
            temp_session = memory_manager.get_or_create_session(temp_session_id)
            temp_session.history.clear()
            for msg in described_history:
                temp_session.history.add_message(msg)

            # 后续使用 temp_session_id 进行 Agent 推理
            agent_session_id = temp_session_id
        else:
            # 无图片，使用原始 session_id
            agent_session_id = session_id

        # 解析候选模型列表
        names = [s.strip() for s in str(LLM_NAME).split(",") if s.strip()]

        last_err = None
        max_retries = 2  # 每个模型最多重试 2 次

        try:
            for model_name in names:
                retry_count = 0

                while retry_count <= max_retries:
                    try:
                        # 为当前模型创建临时配置
                        temp_config = CURRENT_LLM.copy()
                        temp_config["NAME"] = model_name

                        # 统一使用 Agent chain（现在图片已转为描述）
                        if model_name not in _CHAIN_CACHE:
                            _CHAIN_CACHE[model_name] = create_agent_chain_with_memory(
                                memory_manager=memory_manager,
                                long_memory_pool=memory_pool,
                                system_prompt=system_prompt,
                                llm_config=temp_config,
                                tools=TOOLS
                            )
                        chain = _CHAIN_CACHE[model_name]

                        from langchain_core.messages import HumanMessage
                        input_msg = HumanMessage(content=user_content)

                        # 添加超时保护（60秒超时）
                        if retry_count > 0:
                            print(f"🔄 模型 {model_name} 第 {retry_count + 1} 次尝试...")

                        try:
                            response = await asyncio.wait_for(
                                asyncio.to_thread(
                                    chain.invoke,
                                    {"input": [input_msg], "long_memory": long_mem},
                                    run_config={"configurable": {"session_id": agent_session_id}}
                                ),
                                timeout=60.0
                            )
                        except asyncio.TimeoutError as timeout_err:
                            last_err = timeout_err
                            retry_count += 1
                            if retry_count <= max_retries:
                                print(f"⏱️ 模型 {model_name} 超时 (尝试 {retry_count}/{max_retries + 1})，重试中...")
                                await asyncio.sleep(1)  # 短暂延迟后重试
                                continue
                            else:
                                print(f"⏱️ 模型 {model_name} 超时，已达最大重试次数，尝试下一个模型")
                                break

                        if isinstance(response, dict):
                            content = response.get("output", "")
                        else:
                            content = response.content if hasattr(response, 'content') else str(response)

                        # 确保 content 是纯文本，不含 Responses API 的 item id
                        content = lc_message_to_text(content) if not isinstance(content, str) else content
                        content = content.strip() if content else ""

                        # 过滤掉 Agent 错误信息
                        if not content or "Agent stopped due to" in content:
                            content = "嗯"

                        out("短期记忆：", memory_manager.get_or_create_session(session_id).history)
                        out("原始信息：", content)
                        out("✅ 使用模型：", model_name)

                        # 异步更新长期记忆
                        def _safe_add_long_memory():
                            try:
                                memory_pool.add_turn(
                                    user_id=user_id,
                                    user_text=user_text,
                                    assistant_text=content
                                )
                            except Exception as e:
                                print("⚠️ [ai_completion] mem0 add_turn 失败：", e)

                        asyncio.create_task(asyncio.to_thread(_safe_add_long_memory))

                        return content

                    except Exception as e:
                        last_err = e
                        retry_count += 1
                        if retry_count <= max_retries:
                            print(f"⚠️ 模型 {model_name} 失败 (尝试 {retry_count}/{max_retries + 1}): {e}，重试中...")
                            await asyncio.sleep(1)
                            continue
                        else:
                            print(f"⚠️ 模型 {model_name} 失败: {e}，已达最大重试次数")
                            break
        finally:
            # 确保清理临时 session（无论成功还是失败）
            if has_image and agent_session_id != session_id:
                try:
                    if agent_session_id in memory_manager._sessions:
                        del memory_manager._sessions[agent_session_id]
                        out("🧹 已清理临时描述 session", agent_session_id)
                except Exception as e:
                    print(f"⚠️ 清理临时 session 失败: {e}")

        # 所有模型都失败，返回默认回复
        print(f"⚠️ [ai_completion] 全部候选模型失败: {last_err}")
        print("💬 返回默认回复")
        return "嗯"

    except Exception as e:
        print(f"⚠️ [ai_completion] 调用 LLM 发生错误: {e}")
        print("💬 返回默认回复")
        return "嗯"


# QQ 消息发送器
async def send_message(websocket, params, retry_count=3):
    """发送消息，支持重试机制"""
    if params is None:
        raise ValueError("params is None")

    for attempt in range(retry_count):
        try:
            await websocket.send(json.dumps({
                "action": "send_msg",
                "params": params
            }))
            # 发送成功
            if attempt > 0:
                print(f"✅ [send_message] 重试成功 (第 {attempt + 1} 次尝试)")
            return True

        except (websockets.exceptions.ConnectionClosed, websockets.exceptions.WebSocketException) as e:
            print(f"⚠️ [send_message] WebSocket 错误 (尝试 {attempt + 1}/{retry_count}): {e}")
            if attempt < retry_count - 1:
                # 等待一小段时间再重试
                await asyncio.sleep(1)
            else:
                print(f"❌ [send_message] 发送失败，已达到最大重试次数")
                return False

        except Exception as e:
            print(f"⚠️ [send_message] 未知错误: {e}")
            return False

    return False

# 记忆函数
async def remember(websocket, event):
    try:
        session_id = calc_session_id(event)

        # 如果会话未初始化，先拉取历史
        if not memory_manager.is_session_initialized(session_id):
            print(f"🔍 首次记忆，正在拉取历史消息...")
            history_msgs = await get_nearby_message(websocket, event, CURRENT_LLM)
            if history_msgs:
                await memory_manager.initialize_with_history(session_id, history_msgs)

        message = event.get("message")
        nickname = event.get("sender").get("nickname")

        # 处理消息，保留完整的多模态内容
        msgs = await process_single_message(message, nickname, CURRENT_LLM)

        for msg in msgs:
            role = msg.get("role")
            content = msg.get("content", [])

            if role == "user" and content:
                # 直接传递多模态内容
                memory_manager.add_user_message(session_id, content)

                # 提取文本用于日志
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

    except Exception as e:
        print(f"⚠️ [remember] 异常: {e}")

# 处理消息事件并发送回复
async def handle_message(websocket, event):
    try:
        session_id = calc_session_id(event)

        msg_type = event.get("message_type")
        out("⏳ 当前会话:", session_id)

        # 调用 chain 生成回复（不再传递 user_content，完全依赖记忆）
        content = await ai_completion(session_id)

        if not content:
            return

        # 发送回复
        await send_message(websocket, build_params("text", event, content))

        # 【关键修复】将 AI 的回复加入上下文记忆
        memory_manager.add_ai_message(session_id, content)
        out("💾 AI 回复已加入上下文:", content[:80])

        # 随机发送表情
        if ran_emoji():
            await send_message(websocket, ran_emoji_content(event))

        print(f"✅ 已回复 {msg_type} 消息: {content}")
        print("#######################################")

    except Exception as e:
        print(f"⚠️ [handle_message] 异常: {e}")


async def qq_bot():
    """主连接函数"""
    # 增加 ping_timeout 和 ping_interval，防止 AI 推理期间连接超时
    async with websockets.connect(
        config.WEBSOCKET_URI,
        ping_interval=20,  # 每 20 秒发送一次 ping
        ping_timeout=60    # ping 超时时间 60 秒（足够 AI 推理完成）
    ) as ws:
        print("✅ 成功连接到WebSocket服务器")

        fortune_scheduler = setup_daily_fortune_scheduler(
            websocket=ws,
            target_groups=FORTUNE_GROUPS,
            push_hour=8,
            push_minute=0,
            theme="random"
        )

        async for message in ws:
            try:
                event = json.loads(message)
                # 响应"戳一戳"
                if event.get("post_type") == "notice" and event.get("sub_type") == "poke" and event.get(
                        "target_id") == config.SELF_USER_ID:
                    await send_message(ws, build_params_text_only(event, ran_rep_text_only()))
                    continue

                # 过滤非消息事件
                if event.get("post_type") != "message":
                    continue

                my_event = await special_event(event)
                if my_event:
                    if my_event.get("message"):
                        await send_message(ws, my_event)
                    continue

                # 并发处理消息，避免阻塞其他消息
                asyncio.create_task(_process_message_task(ws, event))

            except json.JSONDecodeError:
                print("⚠️ 收到非JSON格式消息")
            except Exception as e:
                print(f"⚠️ 处理消息时发生错误: {e}")


async def _process_message_task(ws, event):
    """异步处理单个消息的任务"""
    try:
        await remember(ws, event)
        if rep(event, memory_manager):
            await handle_message(ws, event)
    except Exception as e:
        print(f"⚠️ [_process_message_task] 处理消息异常: {e}")
        import traceback
        traceback.print_exc()



if __name__ == "__main__":
    while True:
        try:
            asyncio.get_event_loop().run_until_complete(qq_bot())

        except (websockets.ConnectionClosed, OSError, ConnectionRefusedError, TimeoutError, websockets.InvalidURI,
                websockets.InvalidHandshake, websockets.WebSocketException):

            print("⏱️ 连接断开，尝试重连...")
            time.sleep(3)
            continue

        except KeyboardInterrupt:
            print("🚫 程序已终止")
            break
