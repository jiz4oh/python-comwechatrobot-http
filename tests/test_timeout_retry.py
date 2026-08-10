import os
import sys
import time
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wechatrobot.Api import Api
from wechatrobot.WeChatRobot import WeChatRobot


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.content = payload if isinstance(payload, bytes) else b""

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def message(msgid):
    return {
        "msgid": msgid,
        "message": f"text-{msgid}",
        "type": 1,
        "sender": "wxid_a",
        "isSendMsg": 0,
        "isSendByPhone": 1,
    }


class ApiTimeoutTest(unittest.TestCase):
    def test_control_request_uses_finite_timeout(self):
        api = Api()
        api.request_timeout = 5.0
        with patch("wechatrobot.Api.requests.post", return_value=FakeResponse(b'{"result":"OK"}')) as mocked:
            api.GetSelfInfo()
        self.assertEqual(mocked.call_args.kwargs["timeout"], 5.0)

    def test_send_request_uses_send_timeout(self):
        api = Api()
        api.send_timeout = 60.0
        with patch("wechatrobot.Api.requests.post", return_value=FakeResponse(b'{"result":"OK"}')) as mocked:
            api.SendText(wxid="wxid_a", msg="hello")
        self.assertEqual(mocked.call_args.kwargs["timeout"], 60.0)

    def test_timeouts_read_from_environment(self):
        with patch.dict(
            os.environ,
            {"WECHATROBOT_API_TIMEOUT": "7.5", "WECHATROBOT_SEND_API_TIMEOUT": "42"},
            clear=False,
        ):
            api = Api()
        self.assertEqual(api.request_timeout, 7.5)
        self.assertEqual(api.send_timeout, 42.0)


class DispatchRetryTest(unittest.TestCase):
    def make_robot(self):
        with patch.dict(
            os.environ,
            {"WECHATROBOT_DISPATCH_RETRY_TIMES": "2", "WECHATROBOT_DISPATCH_RETRY_BASE_SECONDS": "0.01"},
            clear=False,
        ):
            return WeChatRobot()

    def test_failed_dispatch_retries_then_alerts_and_drops(self):
        robot = self.make_robot()
        dispatched = []

        def callback(msg):
            if msg["msgid"].startswith("bad"):
                raise RuntimeError("dispatch boom")
            dispatched.append(msg["msgid"])

        robot._receive_callback = callback
        payload = {"messages": [message("bad1"), message("ok"), message("bad2")]}
        with patch("wechatrobot.WeChatRobot.requests.post", return_value=FakeResponse(payload)):
            self.assertTrue(robot._pull_once())

        self.assertEqual(dispatched, ["ok"])
        self.assertEqual(len(robot._retry_queue), 2)

        for _ in range(2):
            robot._retry_queue = deque(
                (msg, attempts, time.monotonic() - 1)
                for msg, attempts, _ in robot._retry_queue
            )
            robot._process_retry_queue()

        self.assertEqual(robot._retry_queue, deque())
        self.assertEqual(dispatched, ["ok"])

    def test_retry_succeeds_before_exhaustion(self):
        robot = self.make_robot()
        dispatched = []
        attempts = {"bad": 0}

        def callback(msg):
            if msg["msgid"] == "bad" and attempts["bad"] == 0:
                attempts["bad"] += 1
                raise RuntimeError("first attempt boom")
            dispatched.append(msg["msgid"])

        robot._receive_callback = callback
        with patch("wechatrobot.WeChatRobot.requests.post", return_value=FakeResponse({"messages": [message("bad")]})):
            robot._pull_once()

        self.assertEqual(dispatched, [])
        self.assertEqual(len(robot._retry_queue), 1)
        msg, retry_attempts, _ = robot._retry_queue[0]
        self.assertEqual(retry_attempts, 1)
        robot._retry_queue = deque([(msg, retry_attempts, time.monotonic() - 1)])
        robot._process_retry_queue()

        self.assertEqual(dispatched, ["bad"])
        self.assertEqual(robot._retry_queue, deque())


if __name__ == "__main__":
    unittest.main()
