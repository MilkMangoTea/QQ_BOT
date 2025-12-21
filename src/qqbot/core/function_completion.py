import base64
import urllib.parse
import re
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
from langchain_core.pydantic_v1 import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, FewShotChatMessagePromptTemplate, MessagesPlaceholder
from langchain_core.caches import InMemoryCache
from langchain_core.globals import set_llm_cache
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.runnables.history import RunnableWithMessageHistory


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


# 轻量 httpx Client
HTTPX_LIMITS = httpx.Limits(max_connections=100, max_keepalive_connections=20, keepalive_expiry=20.0)
HTTPX_TIMEOUT = httpx.Timeout(connect=10.0, read=25.0, write=10.0, pool=10.0)
HTTP_CLIENT = httpx.Client(limits=HTTPX_LIMITS, timeout=HTTPX_TIMEOUT, http2=True)

# 模型配置
_DEEPSEEK = config.LLM.get("DEEPSEEK-V3", {})
_DEEPSEEK_NAME = _DEEPSEEK.get("NAME")
_DEEPSEEK_URL = _DEEPSEEK.get("URL")
_DEEPSEEK_KEY = _DEEPSEEK.get("KEY")


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
    category: str = Field(description="FOLLOWUP | QUESTION | CHITCHAT | OTHER | NOISE")
    confidence: float = Field(ge=0, le=1, description="0~1 confidence score")


# few-shot 示例
_EXAMPLES = [
    {
        "input": "上下文: 在聊代理设置。 当前消息: Mac上怎么全局代理？",
        "output": {"should_reply": True, "category": "QUESTION", "confidence": 0.9}
    },
    {
        "input": "上下文: 机器人刚给了步骤。 当前消息: 证书在哪导入？",
        "output": {"should_reply": True, "category": "FOLLOWUP", "confidence": 0.9}
    },
    {
        "input": "上下文: 无。 当前消息: ？？？",
        "output": {"should_reply": False, "category": "NOISE", "confidence": 0.85}
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
你是“群聊消息路由器”。目标：基于上下文与当前消息，按【猫娘】人设判断此刻是否应该发言。
只返回 JSON，键固定且唯一：
{"should_reply": true/false, "category": "FOLLOWUP|QUESTION|CHITCHAT|OTHER|NOISE", "confidence": 0~1}
不要输出解释、前后缀或多余文本。

【人设基调】
- 名为 MilkMangoTower,但 mmt 并不是名字的缩写,轻松俏皮、略傲娇；偏短句，偶尔口癖（如“喵/～”）。愿意接轻社交与情绪安抚，但不强行插话。

【优先回复（强触发）】
1) 明确问题/求助，能给具体解法或方向（如“怎么/为何/能否/在哪设置”等）。
2) 对机器人先前内容的追问、澄清、继续推进（FOLLOWUP）。
3) 有明确情绪需要安抚或鼓励（沮丧、道歉、感谢、祝福），且与最近上下文有关联。

【可选回复（弱触发，视上下文而定）】
- 轻社交寒暄、玩梗、致谢、简短互动，若与最近话题或人设有明显关联（CHITCHAT）。

【不回复（强抑制）】
- 无信息量或扰动：纯无意义符号/重复标点/口水（例如“？？？”，“……”），刷屏，广告拉群。
- 与当前话题和人设无关的长篇争论或敏感对立话题（非安抚/纠偏场景）。
- 纯转发或模板通知，机器人难以增量提供价值。
- 没有明确对话对象（如你），大概率与其他人交流。
- 明确说明不要回复

【分类口径】
- FOLLOWUP：基于机器人近期输出的继续追问/澄清/推进。
- QUESTION：明确求助/问题。
- CHITCHAT：寒暄、玩笑、致谢、祝福、轻度感叹或情绪交流。
- OTHER：与主题相关但不符合以上三类，且不属于噪音。
- NOISE：广告/刷屏/无信息量/与上下文完全脱节的扰动。

【信心分参考（仅作打分倾向）】
- 明确问题 +0.30；FOLLOWUP +0.30；情绪安抚/致谢且有关联 +0.20；轻社交有关联 +0.15；
- 明显无关 -0.30；噪音/广告 -0.40；
- 倾向短句：若是长段无问句且无明确诉求，可 -0.10；
- 综合后在 0~1 内给出合理分值。
"""

_PROMPT = ChatPromptTemplate.from_messages([
    ("system", "{rules}"),
    _FEWSHOT,
    ("human",
     "【群聊最近上下文】\n{ctx}\n\n"
     "【当前消息】\n{user_message}\n"
     "只返回 JSON。"
     ),
]).partial(rules=_RULES_TEXT)

# 供外部调用
def create_chat_llm(llm_config):
    """根据配置创建 ChatOpenAI 实例"""
    return ChatOpenAI(
        model=llm_config["NAME"],
        api_key=llm_config["KEY"],
        base_url=llm_config["URL"],
        temperature=0.7,
        timeout=15.0,
        max_retries=0,
        http_client=HTTP_CLIENT,
    )

def _make_llm():
    if not (_DEEPSEEK_NAME and _DEEPSEEK_URL and _DEEPSEEK_KEY):
        raise RuntimeError("DEEPSEEK(OpenAI-compatible) 未配置：请在 config.LLM['DEEPSEEK-V3'] 中设置 NAME/URL/KEY")
    return ChatOpenAI(
        model=_DEEPSEEK_NAME,
        api_key=_DEEPSEEK_KEY,
        base_url=_DEEPSEEK_URL,
        temperature=0.0,
        timeout=12,
        max_retries=2,
    )


set_llm_cache(InMemoryCache())

# 缓存 decision chain，避免每次都创建新实例
_CACHED_DECISION_CHAIN = None

def _decision_chain():
    global _CACHED_DECISION_CHAIN
    if _CACHED_DECISION_CHAIN is None:
        llm = _make_llm()
        _CACHED_DECISION_CHAIN = _PROMPT | llm.with_structured_output(Decision)
    return _CACHED_DECISION_CHAIN


# LangChain 判定
def should_reply_langchain(event: Dict[str, Any], memory_manager, session_id: str) -> bool:
    """
    - 图片-only：直接 False（仅依据分段 type）
    - 无文本：直接 False
    - 其余交给 LangChain 结构化输出链
    """
    try:
        if is_image_only_event(event):
            print("跳过：图片-only/无有效文本")
            return False
    except Exception:
        pass

    curr_text = _extract_text(event)
    if not curr_text:
        return False

    # 从 MemoryManager 获取最近上下文
    ctx_lines = memory_manager.get_recent_dialog_lines(session_id, take_n=10, max_chars_per_line=240)
    ctx = "\n".join(ctx_lines) if ctx_lines else "（无）"

    try:
        dec = _decision_chain().invoke({"ctx": ctx, "user_message": curr_text})
        should = bool(dec.should_reply)
        print("LC 判定:", {
            "should": should,
            "cat": dec.category,
            "conf": dec.confidence,
            "curr": curr_text[:48]
        })
        if (dec.confidence or 0) < 0.55 and dec.category != "QUESTION":
            return False
        return should
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
    from langchain.agents import AgentExecutor, create_react_agent
    from langchain_core.prompts import PromptTemplate

    llm = create_chat_llm(llm_config)

    # ReAct Agent prompt
    react_prompt = PromptTemplate.from_template(
        """{system_prompt}

【相关长期记忆】
{long_memory}

【历史对话】
{history}

【当前输入】
{input}

你可以使用以下工具：
{tools}

工具名称列表: {tool_names}

回答格式：
Question: 用户的问题
Thought: 我的思考
Action: 工具名（如果需要）
Action Input: 工具输入（如果需要）
Observation: 工具结果（系统自动填充）
Thought: 我现在知道最终答案了
Final Answer: 最终回复

关键规则：
1. 数学计算必须用 numpy_calc 工具
2. 工具返回结果后，立即输出 "Thought: 我现在知道最终答案了" 然后 "Final Answer: ..."
3. 不需要工具时直接给 Final Answer

{agent_scratchpad}"""
    )

    agent = create_react_agent(llm, tools, react_prompt)

    agent_executor = AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=True,
        handle_parsing_errors=True,
        max_iterations=3,
        early_stopping_method="generate"
    )

    def invoke_with_memory(self, inputs, config=None):
        if config is None:
            config = {}
        session_id = config.get("configurable", {}).get("session_id")

        # 获取历史消息列表
        if session_id:
            session = memory_manager.get_or_create_session(session_id)
            history_msgs = session.history.messages if hasattr(session.history, 'messages') else []
        else:
            history_msgs = []

        history_text = "\n".join([
            f"{'用户' if isinstance(msg, HumanMessage) else 'AI'}: {msg.content if isinstance(msg.content, str) else str(msg.content)}"
            for msg in history_msgs[-10:]
        ])

        input_msgs = inputs.get("input", [])
        input_text = ""
        for msg in input_msgs:
            if hasattr(msg, 'content'):
                if isinstance(msg.content, list):
                    input_text = "\n".join([
                        p.get("text", "") for p in msg.content if isinstance(p, dict) and p.get("type") == "text"
                    ])
                else:
                    input_text = msg.content

        result = agent_executor.invoke({
            "system_prompt": system_prompt,
            "long_memory": inputs.get("long_memory", ""),
            "history": history_text,
            "input": input_text,
        })

        return {"output": result.get("output", "")}

    return type('ChainWithMemory', (), {'invoke': invoke_with_memory})()