import json
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

    def test_mark_as_read_posts_chat_wxid_to_type_49(self):
        api = Api()
        with patch(
            "wechatrobot.Api.requests.post",
            return_value=FakeResponse(b'{"result":"OK","msg":1}'),
        ) as mocked:
            response = api.MarkAsRead(wxid="wxid_a")

        self.assertEqual(response, {"result": "OK", "msg": 1})
        self.assertTrue(mocked.call_args.args[0].endswith("/api/?type=49"))
        self.assertEqual(json.loads(mocked.call_args.kwargs["data"]), {"wxid": "wxid_a"})


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
        with patch.object(robot, "_native_logged_in", return_value=True), patch(
            "wechatrobot.WeChatRobot.requests.post", return_value=FakeResponse(payload)
        ):
            self.assertTrue(robot._pull_once())

        self.assertEqual(dispatched, ["ok"])
        self.assertEqual(len(robot._retry_queue), 2)

        for _ in range(2):
            robot._retry_queue = deque(
                (msg, attempts, time.monotonic() - 1)
                for msg, attempts, _ in robot._retry_queue
            )
            with patch.object(robot, "_native_logged_in", return_value=True):
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
        with patch.object(robot, "_native_logged_in", return_value=True), patch(
            "wechatrobot.WeChatRobot.requests.post", return_value=FakeResponse({"messages": [message("bad")]})
        ):
            robot._pull_once()

        self.assertEqual(dispatched, [])
        self.assertEqual(len(robot._retry_queue), 1)
        msg, retry_attempts, _ = robot._retry_queue[0]
        self.assertEqual(retry_attempts, 1)
        robot._retry_queue = deque([(msg, retry_attempts, time.monotonic() - 1)])
        with patch.object(robot, "_native_logged_in", return_value=True):
            robot._process_retry_queue()

        self.assertEqual(dispatched, ["bad"])
        self.assertEqual(robot._retry_queue, deque())


class LoginGateTest(unittest.TestCase):
    def test_native_logged_in_accepts_self_info(self):
        robot = WeChatRobot()
        with patch.object(robot.api, "GetSelfInfo", return_value={"data": {"wxId": "wxid_a"}}):
            self.assertTrue(robot._native_logged_in())

    def test_native_logged_in_rejects_login_required(self):
        robot = WeChatRobot()
        with patch.object(robot.api, "GetSelfInfo", return_value={"data": "请先登录微信."}):
            self.assertFalse(robot._native_logged_in())

    def test_consume_holds_bridge_messages_when_not_logged_in(self):
        robot = WeChatRobot()
        bridge_calls = []

        def fake_post(*args, **kwargs):
            bridge_calls.append((args, kwargs))
            return FakeResponse({"messages": []})

        with patch.object(robot, "_native_logged_in", return_value=False), patch(
            "wechatrobot.WeChatRobot.requests.post", side_effect=fake_post
        ), patch(
            "wechatrobot.WeChatRobot.time.sleep", side_effect=[None, KeyboardInterrupt]
        ):
            with self.assertRaises(KeyboardInterrupt):
                robot._consume_forever()

        self.assertEqual(bridge_calls, [])

    def test_login_required_dispatch_is_deferred_not_dropped(self):
        robot = WeChatRobot()

        def callback(msg):
            raise RuntimeError("dispatch boom while not logged in")

        robot._receive_callback = callback
        payload = {"messages": [message("stuck")]}
        with patch.object(robot, "_native_logged_in", return_value=False), patch(
            "wechatrobot.WeChatRobot.requests.post", return_value=FakeResponse(payload)
        ):
            robot._pull_once()

        self.assertEqual(len(robot._retry_queue), 1)
        for _ in range(10):
            robot._retry_queue = deque(
                (msg, attempts, time.monotonic() - 1)
                for msg, attempts, _ in robot._retry_queue
            )
            with patch.object(robot, "_native_logged_in", return_value=False):
                robot._process_retry_queue()

        self.assertEqual(len(robot._retry_queue), 1)


if __name__ == "__main__":
    unittest.main()
