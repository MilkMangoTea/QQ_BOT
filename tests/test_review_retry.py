#!/usr/bin/env python3
"""Offline checks for review-only retries, bounded failures and cancellation."""

import asyncio
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, call, patch

import httpx
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from openai import APIConnectionError, APIStatusError, APITimeoutError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MY_QQ_ID", "0")
os.environ.setdefault("BOT_QQ_ID", "0")

from src.qqbot.config import config
from src.qqbot.core.function_agent import REVIEW_CHECKS, run_reviewed_agent


def review(approved=True):
    checks = {key: {"status": "通过", "reason": "符合本轮要求"} for key in REVIEW_CHECKS}
    if not approved:
        checks["persona"] = {"status": "不通过", "reason": "需要修正角色表达"}
    return AIMessage(content=json.dumps(checks, ensure_ascii=False))


def timeout():
    return APITimeoutError(request=httpx.Request("POST", "https://example.com/review"))


class ReviewRetryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.settings = dict(config.AGENT_CONFIG)
        self.messages = [HumanMessage(content="群友: 在吗")]
        self.draft = AIMessage(content='{"reply":"在喵","emoji":null}')

    async def run_agent(self, model, executor=None, async_mode=True, render_enabled=False):
        return await run_reviewed_agent(
            executor, model, self.messages, "原始人格", "输出 reply/emoji JSON",
            self.settings, render_enabled, lambda msg: msg.content, async_mode=async_mode,
        )

    async def test_timeout_retries_same_review_without_regenerating_or_repeating_tools(self):
        evidence = ToolMessage(content="已有搜索证据", tool_call_id="search", name="deepseek_search")
        executor = Mock(ainvoke=AsyncMock(return_value={
            "messages": [*self.messages, evidence, self.draft],
        }))
        model = Mock(ainvoke=AsyncMock(side_effect=[timeout(), timeout(), review()]))
        with patch("src.qqbot.core.function_agent.asyncio.sleep", new_callable=AsyncMock) as sleep, \
                patch("src.qqbot.core.function_agent.out") as log:
            result = await self.run_agent(model, executor)
        executor.ainvoke.assert_awaited_once()
        self.assertEqual(model.ainvoke.await_count, 3)
        first_request = model.ainvoke.call_args_list[0].args[0]
        self.assertIn(evidence, first_request)
        self.assertIs(first_request[-3], self.draft)
        for request in model.ainvoke.call_args_list[1:]:
            self.assertIs(request.args[0], first_request)
        self.assertEqual(sleep.await_args_list, [call(1.0), call(2.0)])
        self.assertTrue(result["review_approved"])
        self.assertEqual(result["output"], self.draft.content)
        self.assertEqual(result["revision_count"], 0)
        self.assertIn("第 3/3 次调用", str(log.call_args_list))

    async def test_exhausted_retries_block_candidate_and_clean_images(self):
        image_id = "ab" * 16
        image = ToolMessage(content="PNG", tool_call_id="render", name="render_to_png",
                            artifact={"type": "rendered_image", "id": image_id})
        executor = Mock(ainvoke=AsyncMock(return_value={
            "messages": [*self.messages, image, self.draft],
        }))
        model = Mock(ainvoke=AsyncMock(side_effect=[timeout(), timeout(), timeout()]))
        with patch("src.qqbot.core.function_agent.asyncio.sleep", new_callable=AsyncMock), \
                patch("src.qqbot.core.function_agent.out"), \
                patch("src.qqbot.core.function_render.rendered_image_path") as path:
            result = await self.run_agent(model, executor, render_enabled=True)
        self.assertEqual(model.ainvoke.await_count, 3)
        executor.ainvoke.assert_awaited_once()
        self.assertEqual(result["review_status"], "review_failed")
        self.assertIsNone(result["review_approved"])
        self.assertEqual(result["output"], "")
        self.assertEqual(result["rendered_image_ids"], [])
        path.return_value.unlink.assert_called_once_with(missing_ok=True)

    async def test_transient_errors_retry_but_permanent_errors_stop(self):
        request = httpx.Request("POST", "https://example.com/review")
        errors = [(timeout(), True),
                  (APIConnectionError(request=request), True),
                  (httpx.ReadTimeout("read timed out"), True),
                  (httpx.ConnectError("connection failed"), True),
                  (TimeoutError("timed out"), True),
                  (asyncio.TimeoutError("async timed out"), True),
                  (RuntimeError("invalid model configuration"), False)]
        for status in (400, 401, 403, 408, 409, 422, 429, 500, 502, 503):
            errors.append((APIStatusError("API error", response=httpx.Response(status, request=request),
                                          body=None), status in (408, 409, 429) or status >= 500))
        for error, retryable in errors:
            with self.subTest(error=type(error).__name__, status=getattr(error, "status_code", None)), \
                    patch("src.qqbot.core.function_agent.asyncio.sleep", new_callable=AsyncMock) as sleep, \
                    patch("src.qqbot.core.function_agent.out"):
                model = Mock(ainvoke=AsyncMock(side_effect=[self.draft, error, review()]))
                result = await self.run_agent(model)
                self.assertEqual(model.ainvoke.await_count, 3 if retryable else 2)
                self.assertEqual(result["review_status"], "approved" if retryable else "review_failed")
                self.assertEqual(sleep.await_count, 1 if retryable else 0)

    async def test_retry_can_be_disabled(self):
        self.settings["REVIEW_MAX_RETRIES"] = 0
        model = Mock(ainvoke=AsyncMock(side_effect=[self.draft, timeout(), review()]))
        with patch("src.qqbot.core.function_agent.asyncio.sleep", new_callable=AsyncMock) as sleep, \
                patch("src.qqbot.core.function_agent.out"):
            result = await self.run_agent(model)
        self.assertEqual(model.ainvoke.await_count, 2)
        self.assertEqual(result["review_status"], "review_failed")
        sleep.assert_not_awaited()

    async def test_invalid_review_stops_without_retry_or_regeneration(self):
        model = Mock(ainvoke=AsyncMock(side_effect=[self.draft, AIMessage(content="bad review"), review()]))
        with patch("src.qqbot.core.function_agent.asyncio.sleep", new_callable=AsyncMock) as sleep, \
                patch("src.qqbot.core.function_agent.out"):
            result = await self.run_agent(model)
        self.assertEqual(model.ainvoke.await_count, 2)
        self.assertEqual(result["review_status"], "review_failed")
        self.assertEqual(result["output"], "")
        sleep.assert_not_awaited()

    async def test_each_revision_gets_its_own_review_retry_budget(self):
        model = Mock(ainvoke=AsyncMock(side_effect=[
            self.draft, timeout(), timeout(), review(False),
            AIMessage(content="修正后的候选"), timeout(), timeout(), review(),
        ]))
        with patch("src.qqbot.core.function_agent.asyncio.sleep", new_callable=AsyncMock) as sleep, \
                patch("src.qqbot.core.function_agent.out"):
            result = await self.run_agent(model)
        self.assertEqual(model.ainvoke.await_count, 8)
        self.assertEqual(result["revision_count"], 1)
        self.assertEqual(result["output"], "修正后的候选")
        self.assertEqual(sleep.await_args_list, [call(1.0), call(2.0), call(1.0), call(2.0)])

    async def test_sync_invocations_retry_using_only_sync_client(self):
        model = Mock(invoke=Mock(side_effect=[self.draft, timeout(), review()]), ainvoke=AsyncMock())
        with patch("src.qqbot.core.function_agent.asyncio.sleep", new_callable=AsyncMock), \
                patch("src.qqbot.core.function_agent.out"):
            result = await self.run_agent(model, async_mode=False)
        self.assertTrue(result["review_approved"])
        self.assertEqual(model.invoke.call_count, 3)
        model.ainvoke.assert_not_awaited()

    async def test_turn_timeout_interrupts_review_backoff(self):
        self.settings["REVIEW_RETRY_DELAY"] = 60.0
        model = Mock(ainvoke=AsyncMock(side_effect=[self.draft, timeout(), review()]))
        with patch("src.qqbot.core.function_agent.out"):
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(self.run_agent(model), timeout=0.05)
        self.assertEqual(model.ainvoke.await_count, 2)


if __name__ == "__main__":
    unittest.main()
