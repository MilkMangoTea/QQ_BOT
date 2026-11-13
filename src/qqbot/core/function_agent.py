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
判断最后一条候选回复能否作为 MilkMangoTower 在当前群聊中的真实发言直接发送。结合完整人格提示词、聊天上下文、原始请求及本轮实际工具结果，逐项检查：
- 意图：理解谁在对谁说话，以及对方期待什么回应。区分事实提问、个人好恶、建议、玩梗、假设和情绪交流；检查候选是否真正接住对方的话，是否把主观交流误答成客观介绍，或用复述、条件句和空泛分析回避回应。
- 人格：先从原始人格中找出与本轮内容相关的设定，再逐条对照候选表达的个人偏好、情感指向、立场、关系和行为，包括自然表达中隐含的态度。reason 须引用最相关的设定原文和候选对应表达，说明是否冲突，不能只凭口癖或语气判定。任一相关设定被明确违背即不通过，其他性格特征的符合不能抵消冲突。只检查本轮相关设定，不要求展示全部人格；客观描述他人或介绍事实不等于表达自身偏好，不为体现人格歪曲事实或添加无关内容。
- 自然度：判断候选是不是这个人物此刻会说的话，是否自然承接前文。留意普通 AI 回答套角色口癖、客服腔、无意义复述、空泛总结和不必要的展开。角色可以冷淡、简短、嘴硬或说些信息量不大的话，不因措辞普通就判定不合格。闲聊通常保持一两句，认真解释时可按需展开。
- 完成度与事实：检查是否回答核心问题、表达应有的选择或态度，并完成多对象、多条件和多项任务。检索、计算和执行结论以实际可见的工具结果为准，不能相信候选自称完成；多个目标分别核对，稳定常识和主观看法不要求额外检索。
- 格式：检查 reply/emoji JSON、可选表情及人格中的硬性表达要求。正文不能带说话者前缀、后台内容或工具日志；出处和链接按用户实际要求提供。按规则本意判断，区分分句与完整句子，不因句末语气符号自行增加禁令；声称违反字数限制时须先逐字核对。
【判定要求】
- 判定依据只描述候选、上下文及工具结果中可见的内容；发现错误直接指出错误，不猜测作者是否故意、是否为了玩梗或是否想迎合。
- 每项返回“通过”“不通过”或“不适用”，并附一句具体依据；不通过时指出具体表达或遗漏，以及必要的修改方向。
- 相关设定存在明确冲突时必须判为不通过，不能因回复自然、任务完成或带有口癖而放行。
- 不为凑检查结果强找缺陷，也不为了寻找更好的措辞反复退回合格回复。第一份合格候选即可发送。
- 任一项不通过，整体就不通过；整体结论由程序汇总，不另填总判定。
【返回格式】
本次只返回以下审核 JSON，替代面向群友的 reply/emoji 输出要求。五项不可省略，status 选择“通过”“不通过”或“不适用”，reason 填写简短依据。不输出完整思维过程或改写后的回复。
{
  "intent": {"status": "通过", "reason": "具体依据"},
  "persona": {"status": "通过", "reason": "具体依据"},
  "naturalness": {"status": "通过", "reason": "具体依据"},
  "completeness": {"status": "通过", "reason": "具体依据"},
  "format": {"status": "通过", "reason": "具体依据"}
}
"""


REVIEW_CHECKS = {
    "intent": "意图",
    "persona": "人格",
    "naturalness": "自然度",
    "completeness": "完成度与事实",
    "format": "格式",
}


def _parse_review(content):
    if not isinstance(content, str):
        return None
    text = content.strip()
    if text.startswith("```") and text.endswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        decision = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(decision, dict) or set(decision) != set(REVIEW_CHECKS):
        return None
    checks = {}
    failures = []
    for key, label in REVIEW_CHECKS.items():
        item = decision[key]
        if not isinstance(item, dict):
            return None
        status = item.get("status")
        reason = item.get("reason")
        if (status not in ("通过", "不通过", "不适用")
                or not isinstance(reason, str) or not reason.strip()):
            return None
        checks[key] = {"status": status, "reason": reason.strip()[:1500]}
        if status == "不通过":
            failures.append(f"{label}：{checks[key]['reason']}")
    return not failures, "\n".join(failures), checks


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
    review_checks = {}
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
        review_checks = {}
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
        approved, feedback, review_checks = decision
        out("回复后台验收", {"通过": approved, "修正次数": revisions,
                            "逐项结果": {REVIEW_CHECKS[key]: item for key, item in review_checks.items()},
                            "反馈": feedback})
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
            "review_checks": review_checks,
            "review_status": review_status}
