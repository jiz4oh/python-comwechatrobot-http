import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wechatrobot.Api import Api
from wechatrobot.Modles import WECHAT_GET_CDN


class FakeResponse:
    content = b'{"result":"OK","path":"C:/sticker.png"}'


class GetCdnTest(unittest.TestCase):
    def test_posts_message_reference_as_json_string(self):
        api = Api()
        with patch(
            "wechatrobot.Api.requests.post",
            return_value=FakeResponse(),
        ) as post:
            response = api.GetCdn(msgid=7744938917580967084)

        self.assertEqual(response["path"], "C:/sticker.png")
        self.assertTrue(post.call_args.args[0].endswith(
            "/api/?type={}".format(WECHAT_GET_CDN)
        ))
        self.assertEqual(
            json.loads(post.call_args.kwargs["data"]),
            {"msgid": "7744938917580967084"},
        )

    def test_preserves_local_message_reference(self):
        api = Api()
        with patch(
            "wechatrobot.Api.requests.post",
            return_value=FakeResponse(),
        ) as post:
            api.GetCdn(msgid="local:7:123")

        self.assertEqual(
            json.loads(post.call_args.kwargs["data"]),
            {"msgid": "local:7:123"},
        )


if __name__ == "__main__":
    unittest.main()
