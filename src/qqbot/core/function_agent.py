"""Bounded reply review that preserves the agent's tool evidence across revisions."""

import json
import traceback

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.callbacks.manager import CallbackManager

from src.qqbot.core.function_render import cleanup_rendered_images as _cleanup_images, rendered_image_ids
from src.qqbot.utils.console import out


REVIEW_INSTRUCTION = """
【后台验收，不是给用户的回复】
你的任务是判断这条回复能否作为 MilkMangoTower 在当前群聊中的真实发言直接发送。
先理解当前交流中谁在说话、想表达什么、期待怎样的回应，再看候选实际完成了什么。
【1. 人格、自然语言与去八股——核心】
结合完整人格提示词和当前群聊，判断候选是不是这个人物此刻会说的话。
关注人物如何理解对方、选择回应、表达态度，以及语言是否自然承接前文。
尤其留意普通 AI 回答套上角色口癖、用复述代替回应、用空泛分析回避个人态度、对已经说清的内容反复解释等机械表达。
发现这些问题时，判断它们是否真的破坏了交流。角色本来就可能冷淡、简短、重复、嘴硬或说些没什么信息量的话。
语言自然与否取决于具体语境，不要求每句话都鲜明地表现人格，也不以遣词是否足够独特作为验收标准。
【2. 完整性】
对照当前请求检查实际结果。该回答的是否答到核心，该选择的是否明确选择，多对象、多条件和多项任务是否完成了对应要求。
确保对话不存在冗长，列举或重复的内容，避免无信息量的空泛总结、套话或八股。除非设计专业知识，对话长度应当维持在一两句的自然语言水平。
【3. 事实与执行】
检索、计算和执行结论以实际可见的工具结果为准，不以候选自称为准。需要覆盖多个目标时分别核对；稳定常识和主观看法不要求额外检索。
【4. 输出】
核对本轮 reply/emoji JSON、表情选项及完整人格提示词中的硬性格式要求。面向群友的正文不带说话者前缀、后台内容或工具日志。出处和链接按用户实际要求提供。
【判定与迭代】
Counterdefault：第一份合格的候选就是可以发送的成品。
审核重点是发现实际问题，以及寻找更好的表达方式。
如果候选存在明显八股、人格失真、答非所问、事实错误或格式问题，feedback 直接指出具体位置及必要的修改方向。
没有明确缺陷，返回 approved=true。
【返回格式】
只返回一个检查 JSON，覆盖面向用户的 reply/emoji 输出格式。
通过：
{"approved": true, "feedback": ""}
不通过：
{"approved": false, "feedback": "具体缺陷及必要的局部修正"}
不输出思维过程、审核清单或改写后的回复。
"""


def _parse_review(content):
    text = content.strip()
    if text.startswith("```") and text.endswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        decision = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(decision, dict) or type(decision.get("approved")) is not bool:
        return None
    feedback = decision.get("feedback", "")
    if not isinstance(feedback, str) or (not decision["approved"] and not feedback.strip()):
        return None
    return decision["approved"], feedback.strip()[:3000]


def render_status(messages, enabled, to_text):
    if not enabled:
        return "当前模式未启用渲染工具。"
    ids = rendered_image_ids(messages)
    results = [msg for msg in messages
               if getattr(msg, "type", None) == "tool" and getattr(msg, "name", None) == "render_to_png"]
    if ids:
        return f"已生成 {len(ids)} 张 PNG，发送层会随本条回复附图。不要重复源码或编造渲染失败。"
    if results:
        return ("已调用渲染工具，但未生成图片。不要猜测依赖未启动、网络问题或 SVG 正误。实际工具结果：\n"
                + "\n".join(to_text(msg) for msg in results))
    return "本轮未调用 render_to_png，没有生成图片，也没有失败记录。不能编造成功或失败。"


class _TurnTools(BaseCallbackHandler):
    """Track tools even if the graph fails before returning its transcript."""
    def __init__(self):
        self.started = False
        self.results = []
        self.finished = False

    def on_tool_start(self, serialized, input_str, **kwargs):
        self.started = True

    def on_tool_end(self, output, **kwargs):
        self.results.append(output)
        if self.finished:
            _cleanup_images(rendered_image_ids([output]))


async def run_reviewed_agent(executor, llm, messages, system_prompt, output_instruction,
                             settings, render_enabled, to_text, run_config=None, async_mode=True):
    tools = _TurnTools()
    graph_config = dict(run_config or {})
    callbacks = CallbackManager.configure(inheritable_callbacks=graph_config.get("callbacks"))
    callbacks.add_handler(tools, inherit=True)
    graph_config["callbacks"] = callbacks
    keep_images = []
    try:
        result = await _run_reviewed_agent(
            executor, llm, messages, system_prompt, output_instruction, settings,
            render_enabled, to_text, graph_config, async_mode, tools,
        )
        keep_images = result["rendered_image_ids"]
        return result
    finally:
        tools.finished = True
        _cleanup_images([image_id for image_id in rendered_image_ids(tools.results)
                         if image_id not in keep_images])


async def _run_reviewed_agent(executor, llm, messages, system_prompt, output_instruction,
                              settings, render_enabled, to_text, run_config, async_mode, tools):
    """Review real candidates, then resume the same transcript only when needed."""
    messages = list(messages)
    graph_config = dict(run_config or {})
    graph_config["recursion_limit"] = settings["MAX_GRAPH_STEPS"]
    candidate = ""
    approved = None
    revisions = 0
    review_status = "disabled" if not settings["REVIEW_ENABLED"] else "pending"

    async def invoke(target, payload, invoke_config=None):
        kwargs = {"config": invoke_config} if invoke_config is not None else {}
        if async_mode:
            return await target.ainvoke(payload, **kwargs)
        # Synchronous scripts must use the sync HTTP client: an async client's
        # connection pool cannot be reused across successive asyncio.run loops.
        return target.invoke(payload, **kwargs)

    for attempt in range(settings["MAX_REVISIONS"] + 1):
        # A rejected draft must never become the fallback on a failed revision.
        try:
            if executor is not None:
                result = await invoke(executor, {"messages": messages}, graph_config)
                next_messages = result["messages"]
            else:
                response = await invoke(llm, [SystemMessage(content=system_prompt), *messages])
                next_messages = [*messages, response]
            last_message = next_messages[-1] if next_messages else None
            answer = (to_text(last_message).strip()
                      if getattr(last_message, "type", None) == "ai"
                      and not getattr(last_message, "tool_calls", None) else "")
            if not answer:
                raise ValueError("模型没有返回可发送的回复")
        except Exception:
            if not candidate and not tools.started:
                raise
            review_status = "revision_failed" if candidate else "generation_failed"
            out("⚠️ 本轮执行失败，禁止发送候选或重做已开始的工具调用", traceback.format_exc())
            break
        messages = list(next_messages)
        candidate = answer
        revisions = attempt
        if not settings["REVIEW_ENABLED"]:
            break

        approved = None
        status = render_status(messages, render_enabled, to_text)
        try:
            background = "\n".join(to_text(msg) for msg in messages if isinstance(msg, SystemMessage))
            review = await invoke(llm, [
                SystemMessage(content=(
                    f"{system_prompt}\n\n{background}\n\n{output_instruction}\n\n"
                    f"【本轮渲染工具实际状态】\n{status}\n\n{REVIEW_INSTRUCTION}"
                )),
                *(msg for msg in messages if not isinstance(msg, SystemMessage)),
                HumanMessage(content="请验收最后一条候选回复，对照原始用户需求和本轮实际工具结果检查。"),
            ])
            decision = _parse_review(to_text(review))
        except Exception:
            out("⚠️ 后台验收调用失败", traceback.format_exc())
            decision = None
        if decision is None:
            review_status = "review_failed"
            out("⚠️ 后台验收不可用，禁止发送未通过的候选")
            break
        approved, feedback = decision
        out("回复后台验收", {"通过": approved, "修正次数": revisions, "反馈": feedback})
        if approved:
            review_status = "approved"
            break
        if attempt == settings["MAX_REVISIONS"]:
            review_status = "revision_limit"
            out("⚠️ 已达修正上限，候选仍未通过，禁止发送")
            break
        # Preserve tool-call IDs/results and the original user input. Do not rerun
        # completed searches or turn reviewer feedback into a new public dialogue.
        messages.append(SystemMessage(content=(
            "【后台修正指令，不是新用户消息】\n"
            f"{feedback}\n\n【本轮渲染工具实际状态】\n{status}\n"
            "用户的问题没有改变。保持原有角色和聊天语境，只修正指出的问题；"
            "沿用已有工具证据，只为缺项或失败项补充调用。不要重做已完成的搜索或图片。"
            "只给用户最终回复，不提检查意见、修正过程或内部规则。\n"
            f"{output_instruction}"
        )))
        # Start a continuation turn: thinking-mode tool APIs can otherwise treat
        # the previous draft as unfinished and demand its reasoning_content.
        messages.append(HumanMessage(content="请按上述后台修正指令继续处理原始请求，只返回修正后的最终回复。"))

    deliverable = not settings["REVIEW_ENABLED"] or approved is True
    image_ids = rendered_image_ids(messages)
    if not deliverable:
        _cleanup_images(image_ids)
    return {"output": candidate if deliverable else "",
            "rendered_image_ids": image_ids if deliverable else [],
            "review_approved": approved, "revision_count": revisions,
            "review_status": review_status}
