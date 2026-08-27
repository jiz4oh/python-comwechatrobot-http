import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wechatrobot.Api import Api
from wechatrobot.Modles import WECHAT_MSG_REVOKE_MESSAGE


class FakeResponse:
    def __init__(self, payload):
        self.content = json.dumps(payload).encode("utf-8")


class RevokeMessageApiTest(unittest.TestCase):
    def test_revoke_posts_message_identity_and_uses_send_timeout(self):
        api = Api()
        api.send_timeout = 17.5
        with patch(
            "wechatrobot.Api.requests.post",
            return_value=FakeResponse({"msg": 1, "result": "OK"}),
        ) as mocked:
            response = api.RevokeMessage(
                wxid="wxid_a",
                msgid="123456",
                local_id="789",
            )

        self.assertEqual(response, {"msg": 1, "result": "OK"})
        self.assertTrue(mocked.call_args.args[0].endswith(
            f"/api/?type={WECHAT_MSG_REVOKE_MESSAGE}"
        ))
        self.assertEqual(
            json.loads(mocked.call_args.kwargs["data"]),
            {"wxid": "wxid_a", "msgid": "123456", "local_id": "789"},
        )
        self.assertEqual(mocked.call_args.kwargs["timeout"], 17.5)

    def test_revoke_allows_missing_local_id(self):
        api = Api()
        with patch(
            "wechatrobot.Api.requests.post",
            return_value=FakeResponse({"msg": 0, "result": "ERROR"}),
        ) as mocked:
            response = api.RevokeMessage(wxid="wxid_a", msgid="123456")

        self.assertEqual(response["result"], "ERROR")
        self.assertIsNone(json.loads(mocked.call_args.kwargs["data"])["local_id"])


if __name__ == "__main__":
    unittest.main()
