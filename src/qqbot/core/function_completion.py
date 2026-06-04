import base64
import urllib.parse
import re
import json
import httpx
from typing import Any, Dict, List
from src.qqbot.config import config


# 请求构建器
def build_params(type, event, content):
    msg_type = event.get("message_type")
    base = ""
    if type == "text":
        if not content:
            content = "嗯"
        base = {"message": [{"type": "text", "data": {"text": content}}]}
    elif type == "image":
        base = {
            "message": [{"type": "image", "data": {"file": content, "sub_type": 1, "summary": "[色禽图片]"}}]}
    key = "user_id" if msg_type == "private" else "group_id"
    return {**base, "message_type": msg_type, key: event[key]}

# ===== LangChain 相关 =====
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, FewShotChatMessagePromptTemplate, MessagesPlaceholder
from langchain_core.caches import InMemoryCache
from langchain_core.globals import set_llm_cache
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_core.runnables import RunnableLambda


_IMG_TYPES = {"image", "img", "photo", "picture", "sticker"}


def _text_has_meaningful_words(text: str, min_chars: int = 2) -> bool:
    """是否含有有效文字（中英数字至少 min_chars 个）。"""
    if not text:
        return False
    # 去空白与常见无意义字符
    t = re.sub(r"\s+", "", text)
    t = re.sub(r"^[\.\!\?。？！、…~\-—_]+$", "", t)
    return bool(re.search(r"[A-Za-z0-9\u4e00-\u9fff]", t)) and len(t) >= min_chars


def is_image_only_event(event: dict) -> bool:
    """
    仅基于分段 type 判断：如果消息里出现至少一个图片分段(type ∈ _IMG_TYPES)，
    且没有任何包含“有效文字”的 text 分段，则视为“图片-only”。
    """
    has_image = False
    has_text_meaning = False

    for seg in event.get("message", []):
        t = (seg.get("type") or "").lower()
        data = seg.get("data", {}) or {}

        if t in _IMG_TYPES:
            has_image = True
            continue

        if t == "text":
            text = (data.get("text") or "").strip()
            if _text_has_meaningful_words(text):
                has_text_meaning = True

    return has_image and not has_text_meaning

# 把 OpenAI 格式消息转换为 LangChain 格式
def convert_openai_to_langchain(messages):
    result = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", [])

        if role == "system":
            text = "".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
            result.append(SystemMessage(content=text))
        elif role == "user":
            # 支持多模态内容（文本+图片）
            result.append(HumanMessage(content=content))
        elif role == "assistant":
            text = "".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
            result.append(AIMessage(content=text))

    return result


def clean_openai_headers(request: httpx.Request):
    for key in list(request.headers.keys()):
        if key.lower().startswith("x-stainless"):
            del request.headers[key]
    request.headers["User-Agent"] = "Mozilla/5.0"
    request.headers["Accept"] = "text/event-stream"

HTTPX_LIMITS = httpx.Limits(max_connections=100, max_keepalive_connections=20, keepalive_expiry=20.0)
HTTPX_TIMEOUT = httpx.Timeout(connect=10.0, read=25.0, write=10.0, pool=10.0)
HTTP_CLIENT = httpx.Client(
    limits=HTTPX_LIMITS,
    timeout=HTTPX_TIMEOUT,
    http2=True,
    event_hooks={"request": [clean_openai_headers]}
)

# 模型配置
_CURRENT_LLM = config.LLM[config.CURRENT_COMPLETION]
_LLM_NAME = _CURRENT_LLM.get("NAME")
_LLM_URL = _CURRENT_LLM.get("URL")
_LLM_KEY = _CURRENT_LLM.get("KEY")


# 提取当前消息文本
def _extract_text(event) -> str | None:
    parts: List[str] = []
    for seg in event.get("message", []):
        if seg.get("type") == "text":
            t = seg.get("data", {}).get("text", "")
            if t:
                parts.append(t)
        elif seg.get("type") == "at":
            return None
    return "".join(parts).strip()


# LangChain 结构化输出定义
class Decision(BaseModel):
    should_reply: bool = Field(description="Whether the bot should reply.")
    category: str = Field(description="FOLLOWUP | QUESTION | CHITCHAT | TOPIC | OTHER | NOISE")
    target: str = Field(description="BOT | OTHER_USER | GROUP | UNKNOWN")
    interest: float = Field(ge=0, le=1, description="0~1 interest score for proactive participation")
    confidence: float = Field(ge=0, le=1, description="0~1 confidence score")


def lc_content_to_text(content) -> str:
    """兼容 LangChain Responses API 返回的 str / list[dict] content。"""
    if content is None:
        return ""

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = (
                    item.get("text")
                    or item.get("content")
                    or item.get("delta")
                    or ""
                )
                if isinstance(text, str):
                    parts.append(text)
                elif text:
                    parts.append(lc_content_to_text(text))
        return "".join(parts)

    if isinstance(content, dict):
        return lc_content_to_text([content])

    return str(content)


def lc_message_to_text(msg) -> str:
    return lc_content_to_text(getattr(msg, "content", msg))


# few-shot 示例
_EXAMPLES = [
    # 正例：应该回复的情况
    {
        "input": "上下文: 在聊代理设置。 当前消息: Mac上怎么全局代理？",
        "output": {
            "should_reply": True,
            "category": "QUESTION",
            "target": "GROUP",
            "interest": 0.8,
            "confidence": 0.9
        }
    },
    {
        "input": "上下文: 机器人刚给了步骤。 当前消息: 那证书在哪导入？",
        "output": {
            "should_reply": True,
            "category": "FOLLOWUP",
            "target": "BOT",
            "interest": 0.7,
            "confidence": 0.9
        }
    },
    {
        "input": "上下文: 群里在讨论大模型本地部署、显存和量化。 当前消息: 你们觉得 7B 现在还有必要本地跑吗？",
        "output": {
            "should_reply": True,
            "category": "TOPIC",
            "target": "GROUP",
            "interest": 0.9,
            "confidence": 0.82
        }
    },
    # 负例：不应该回复的情况
    {
        "input": "上下文: 群友A说自己买了新键盘。 当前消息: 你在哪买的？",
        "output": {
            "should_reply": False,
            "category": "QUESTION",
            "target": "OTHER_USER",
            "interest": 0.2,
            "confidence": 0.9
        }
    },
    {
        "input": "上下文: 群友们在闲聊。 当前消息: 真的假的？",
        "output": {
            "should_reply": False,
            "category": "QUESTION",
            "target": "UNKNOWN",
            "interest": 0.1,
            "confidence": 0.85
        }
    },
    {
        "input": "上下文: 群友A吐槽游戏更新。 当前消息: 这版本怎么这么抽象？",
        "output": {
            "should_reply": False,
            "category": "QUESTION",
            "target": "GROUP",
            "interest": 0.45,
            "confidence": 0.8
        }
    },
    {
        "input": "上下文: 无。 当前消息: ？？？",
        "output": {
            "should_reply": False,
            "category": "NOISE",
            "target": "UNKNOWN",
            "interest": 0.0,
            "confidence": 0.85
        }
    }
]
_example_prompt = ChatPromptTemplate.from_messages([
    ("human", "{input}"),
    ("ai", "{output}")
])


def _build_fewshot():
    return FewShotChatMessagePromptTemplate(
        examples=_EXAMPLES,
        example_prompt=_example_prompt,
        input_variables=["ctx", "user_message"],
    )


_FEWSHOT = _build_fewshot()

_RULES_TEXT = """
你是”群聊消息路由器”。目标：基于上下文与当前消息，按【猫娘】人设判断此刻是否应该发言。
只返回 JSON，键固定且唯一：
{“should_reply”: true/false, “category”: “...”, “target”: “...”, “interest”: 0~1, “confidence”: 0~1}
不要输出解释、前后缀或多余文本。

【人设基调】
- 名为 MilkMangoTower，但 mmt 并不是名字的缩写，轻松俏皮、略傲娇；偏短句，偶尔口癖（如”喵/～”）。愿意接轻社交与情绪安抚，但不强行插话。

【核心原则】
群聊中默认不回复。不要把”问句”自动视为需要机器人回答。
必须先判断当前消息的对话对象 target：
- BOT：明确 @ 机器人、叫机器人名字、回复机器人上一条消息、或明显在问机器人。
- OTHER_USER：明显在问某个群友、接另一个人的话、点名他人。
- GROUP：向整个群开放讨论，没有特定对象。
- UNKNOWN：对象不明确。

【被动答疑】
只有 target=BOT 时，普通问题/求助才应该回复。

【主动参与】
target=GROUP 且话题有趣、有增量、适合机器人角色时，可以参与。
但不要因为一句普通问句就抢答。
主动参与应当克制，宁缺毋滥。

【不回复】
- target=OTHER_USER 的问题。
- target=UNKNOWN 的短问句，例如”啥？”，”真的假的？”，”为啥？”，”谁知道？”
- 群友之间的普通问答。
- 普通附和、短感叹、口水话。
- 无信息量或扰动：纯无意义符号/重复标点（例如”？？？”，”……”），刷屏，广告拉群。
- 与当前话题和人设无关的长篇争论或敏感对立话题（非安抚/纠偏场景）。
- 纯转发或模板通知，机器人难以增量提供价值。
- 明确说明不要回复。

【分类口径】
- FOLLOWUP：基于机器人近期输出的继续追问/澄清/推进。
- QUESTION：明确求助/问题。
- TOPIC：有深度或技术性的话题讨论，适合机器人贡献见解。
- CHITCHAT：寒暄、玩笑、致谢、祝福、轻度感叹或情绪交流。
- OTHER：与主题相关但不符合以上分类，且不属于噪音。
- NOISE：广告/刷屏/无信息量/与上下文完全脱节的扰动。

【interest 评分（用于主动参与判断）】
- 技术深度话题 +0.4；有趣梗或创意讨论 +0.3；情绪安抚需求 +0.2；
- 普通闲聊 +0.1；明显无关 -0.3；噪音/广告 -0.4；
- 综合后在 0~1 内给出合理分值。

【confidence 评分】
- 明确问题/FOLLOWUP +0.3；情绪安抚/致谢且有关联 +0.2；
- 明显无关 -0.3；噪音/广告 -0.4；
- 综合后在 0~1 内给出合理分值。
"""

_PROMPT_CHAT = ChatPromptTemplate.from_messages([
    ("system", "{rules}"),
    _FEWSHOT,
    ("human",
     "【群聊最近上下文】\n{ctx}\n\n"
     "【当前消息】\n{user_message}\n"
     "只返回 JSON。"
     ),
]).partial(rules=_RULES_TEXT)

_PROMPT_RESPONSES = ChatPromptTemplate.from_messages([
    _FEWSHOT,
    ("human",
     "【群聊最近上下文】\n{ctx}\n\n"
     "【当前消息】\n{user_message}\n"
     "只返回 JSON。"
     ),
])

# 供外部调用
def create_chat_llm(llm_config, system_instructions=None):
    kwargs = {
        "model": llm_config["NAME"],
        "api_key": llm_config["KEY"],
        "base_url": llm_config["URL"],
        "temperature": 0.7,
        "timeout": 60.0,
        "max_retries": 0,
        "http_client": HTTP_CLIENT,
    }
    if llm_config.get("USE_RESPONSES_API"):
        kwargs["use_responses_api"] = True
        kwargs["streaming"] = True
        kwargs["default_headers"] = {"User-Agent": "Mozilla/5.0"}
        if system_instructions:
            kwargs["instructions"] = system_instructions
    return ChatOpenAI(**kwargs)

def _make_llm():
    if not (_LLM_NAME and _LLM_URL and _LLM_KEY):
        raise RuntimeError("LLM 未配置：请在 config.LLM 中设置当前模型的 NAME/URL/KEY")

    model_name = _LLM_NAME.split(",")[0].strip() if "," in str(_LLM_NAME) else _LLM_NAME

    kwargs = {
        "model": model_name,
        "api_key": _LLM_KEY,
        "base_url": _LLM_URL,
        "temperature": 0.0,
        "timeout": 12,
        "max_retries": 2,
        "http_client": HTTP_CLIENT,
    }
    if _CURRENT_LLM.get("USE_RESPONSES_API"):
        kwargs["use_responses_api"] = True
        kwargs["streaming"] = True
        kwargs["default_headers"] = {"User-Agent": "Mozilla/5.0"}

    return ChatOpenAI(**kwargs)


set_llm_cache(InMemoryCache())

# 缓存 decision chain，避免每次都创建新实例
_CACHED_DECISION_CHAIN = None

def _extract_message_text(msg) -> str:
    return lc_message_to_text(msg)


def _parse_decision_message(msg) -> Decision:
    text = lc_message_to_text(msg).strip()

    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError(f"LLM 未返回 JSON: {text}")

    data = json.loads(match.group(0))

    if hasattr(Decision, "model_validate"):
        return Decision.model_validate(data)

    return Decision.parse_obj(data)

def _decision_chain():
    global _CACHED_DECISION_CHAIN
    if _CACHED_DECISION_CHAIN is None:
        llm = _make_llm()

        if _CURRENT_LLM.get("USE_RESPONSES_API"):
            llm = llm.bind(instructions=_RULES_TEXT)
            prompt = _PROMPT_RESPONSES
        else:
            prompt = _PROMPT_CHAT

        _CACHED_DECISION_CHAIN = prompt | llm | RunnableLambda(_parse_decision_message)

    return _CACHED_DECISION_CHAIN


# LangChain 判定
def should_reply_langchain(event: Dict[str, Any], memory_manager, session_id: str) -> bool:
    """
    - 纯图片消息：不主动回复（返回 False，除非被 @ 或私聊）
    - 无文本且无图片：跳过
    - 其余交给 LangChain 结构化输出链判定
    - 添加主动参与冷却机制
    """
    curr_text = _extract_text(event)

    # 如果没有文本，直接返回 False（包括纯图片）
    # 纯图片只有在被 @ 或私聊时才会被处理（由 function.py 的 rep() 控制）
    if not curr_text:
        return False

    # 从 MemoryManager 获取最近上下文（扩大到 20 条以获得更完整的对话背景）
    ctx_lines = memory_manager.get_recent_dialog_lines(session_id, take_n=20, max_chars_per_line=240)
    ctx = "\n".join(ctx_lines) if ctx_lines else "（无）"

    try:
        dec = _decision_chain().invoke({"ctx": ctx, "user_message": curr_text})

        # 检查返回值是否为 None 或无效
        if dec is None:
            print(f"⚠️ LangChain 返回 None，可能 LLM 输出格式错误")
            return False

        # 检查是否有必需的属性
        if not hasattr(dec, 'should_reply'):
            print(f"⚠️ LangChain 返回对象缺少 should_reply 属性: {type(dec)}")
            return False

        should = bool(dec.should_reply)
        target = getattr(dec, 'target', 'UNKNOWN')
        category = getattr(dec, 'category', 'UNKNOWN')
        interest = getattr(dec, 'interest', 0.0)
        confidence = getattr(dec, 'confidence', 0.0)

        print("LC 判定:", {
            "should": should,
            "target": target,
            "cat": category,
            "interest": interest,
            "conf": confidence,
            "curr": curr_text[:48]
        })

        # 如果模型判定不应该回复，直接返回 False
        if not should:
            return False

        # 被动答疑：target=BOT 时可以回复
        directed_to_bot = (target == "BOT")

        # 主动参与：target=GROUP 且 category 属于可主动参与的类型
        proactive_categories = {"TOPIC", "CHITCHAT", "OTHER"}
        is_proactive = (target == "GROUP" and category in proactive_categories)

        # 置信度过滤（修复问题6：在标记冷却之前进行置信度过滤）
        if confidence < 0.55 and category not in {"QUESTION", "FOLLOWUP"}:
            return False

        # 如果是主动参与，检查冷却
        if is_proactive and not directed_to_bot:
            if memory_manager.recent_bot_proactive_reply(session_id, within_seconds=300):
                print("🔇 主动参与冷却中，跳过回复")
                return False
            # 所有过滤通过后，标记本次为主动回复（修复问题6）
            memory_manager.mark_proactive_reply(session_id)

        return True

    except Exception as e:
        print(f"⚠️ LangChain 判定失败: {e}")
        return False

# 从长期记忆池获取相关记忆并格式化为文本
def get_long_memory_text(long_memory_pool, user_id, query):

    try:
        mem_dic = long_memory_pool.get(user_id, query=query)
        if not mem_dic or not isinstance(mem_dic, dict):
            return "（无）"

        lines = []
        for key, val in mem_dic.items():
            lines.append(f"• {key}: {val}")
        return "\n".join(lines) if lines else "（无）"
    except Exception as e:
        print(f"⚠️ 获取长期记忆失败: {e}")
        return "（无）"

# 创建带工具的对话链
def create_agent_chain_with_memory(memory_manager, long_memory_pool, system_prompt, llm_config, tools):
    from langgraph.prebuilt import create_react_agent
    from langchain_core.messages import SystemMessage

    # 检查是否使用 Responses API
    if llm_config.get("USE_RESPONSES_API"):
        # Responses API 模式：不支持工具调用，回退到简单模式
        print("⚠️ Responses API 模式暂不支持工具调用，使用简单 LLM 模式")
        llm = create_chat_llm(llm_config)
        # 不创建 Agent，直接使用 LLM
        agent_executor = None
        persona_llm = llm
    else:
        # 普通模式：支持工具调用
        agent_system_message = """你是一个智能助手，需要根据用户输入决定是否使用工具，并给出客观回复。

关键规则：
1. 只有复杂数学计算（矩阵运算、三角函数、统计分析等）才用 numpy_calc 工具，简单算术直接回答
2. 工具返回结果后，直接给出最终回复
3. 日常对话、闲聊、问候等直接回复
4. 回复必须简洁客观，不要带角色人格"""

        llm = create_chat_llm(llm_config)
        agent_executor = create_react_agent(llm, tools, prompt=agent_system_message)
        persona_llm = llm

    class ChainWrapper:
        def invoke(self, inputs, run_config=None):
            if run_config is None:
                run_config = {}
            if not isinstance(run_config, dict):
                run_config = {}
            session_id = run_config.get("configurable", {}).get("session_id") if run_config else None

            if session_id:
                history = memory_manager.get_history(session_id)
                history_msgs = history.messages
            else:
                history_msgs = []

            # 提取当前输入内容（用于去重比对）
            input_msgs = inputs.get("input", [])
            input_text = ""
            for msg in input_msgs:
                if hasattr(msg, 'content'):
                    input_text = lc_message_to_text(msg)

            # 修复新bug4/5：按文本内容比对去重（统一图文场景）
            # 跳过与当前输入文本完全相同的历史消息
            history_lines = []
            for msg in history_msgs:
                # 如果是 HumanMessage 且文本与当前输入完全相同，跳过
                if isinstance(msg, HumanMessage) and input_text:
                    if lc_message_to_text(msg) == input_text:
                        continue

                role = '用户' if isinstance(msg, HumanMessage) else 'AI'
                text = lc_message_to_text(msg)
                if text:
                    history_lines.append(f"{role}: {text}")
            history_text = "\n".join(history_lines)

            long_memory = inputs.get("long_memory", "")
            context = f"【相关长期记忆】\n{long_memory}\n\n【历史对话】\n{history_text}" if long_memory or history_text else ""

            full_input = f"{context}\n\n{input_text}" if context else input_text

            # 如果没有 agent（Responses API 模式），直接用带角色的 LLM 回复
            if agent_executor is None:
                try:
                    # Responses API 模式：直接用角色人格回复，不需要"客观回复"中间步骤
                    prompt = f"""{system_prompt}

【对话历史】
{history_text}

【用户当前输入】
{input_text}"""

                    llm_response = persona_llm.invoke(prompt)
                    final_answer = lc_message_to_text(llm_response).strip()
                    return {"output": final_answer or "嗯"}
                except Exception as e:
                    print(f"⚠️ LLM 调用失败: {e}")
                    return {"output": "嗯"}

            # 有 agent 的情况：调用工具链
            result = agent_executor.invoke({"messages": [("user", full_input)]})

            raw_answer = ""
            if isinstance(result, dict) and "messages" in result:
                for msg in reversed(result["messages"]):
                    if getattr(msg, "type", None) == "ai":
                        raw_answer = lc_message_to_text(msg).strip()
                        if raw_answer:
                            break

            if raw_answer and "Agent stopped due to" not in raw_answer:
                try:
                    persona_prompt = f"""{system_prompt}

【对话历史】
{history_text}

【用户当前输入】
{input_text}

【你的初步回复】
{raw_answer}

请用你的人格和语气重新表达上述回复，保持核心意思不变，但要符合你的角色设定。直接输出最终回复，不要解释。"""

                    persona_response = persona_llm.invoke(persona_prompt)
                    final_answer = lc_message_to_text(persona_response).strip()
                    return {"output": final_answer}
                except Exception as e:
                    print(f"⚠️ 人格包装失败: {e}")
                    return {"output": raw_answer}

            return {"output": raw_answer if raw_answer else "嗯"}

    return ChainWrapper()