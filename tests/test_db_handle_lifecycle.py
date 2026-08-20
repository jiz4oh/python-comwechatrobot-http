import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests


sys.path.insert(0, str(Path(__file__).parents[1]))

from wechatrobot.Api import Api
from wechatrobot.Modles import WECHAT_DATABASE_INVALIDATE_HANDLES
from wechatrobot.WeChatRobot import WeChatRobot


class DbHandleLifecycleTest(unittest.TestCase):
    def test_bridge_failure_invalidates_cached_handles(self):
        robot = WeChatRobot()
        robot.api.db_handle = {"MicroMsg.db": 0x12345678}

        with patch(
            "wechatrobot.WeChatRobot.requests.post",
            side_effect=requests.ConnectionError("bridge stopped"),
        ):
            self.assertFalse(robot._pull_once())

        self.assertEqual(robot.api.db_handle, {})

    def test_missing_database_handle_refreshes_cache(self):
        api = Api()
        api.db_handle = {"OpenIMContact.db": 2}
        api.GetDatabaseHandles = lambda: {
            "data": [
                {"db_name": "MicroMsg.db", "handle": 1},
                {"db_name": "OpenIMContact.db", "handle": 2},
            ]
        }

        self.assertEqual(api.GetDBHandle("MicroMsg.db"), 1)

    def test_rejected_database_handle_invalidates_cache(self):
        api = Api()
        api.db_handle = {"MicroMsg.db": 1}
        with patch.object(api, "post", return_value={
            "result": "ERROR",
            "err_msg": "database handle unavailable",
            "data": [],
        }):
            response = api.QueryDatabase(db_handle=1, sql="select 1")

        self.assertEqual(response["result"], "ERROR")
        self.assertEqual(api.db_handle, {})

    def test_rejected_named_handle_refreshes_and_retries_once(self):
        api = Api()
        api.db_handle = {"MicroMsg.db": 1}
        responses = iter(
            [
                {
                    "result": "ERROR",
                    "err_msg": "database handle unavailable",
                    "data": [],
                },
                {
                    "result": "OK",
                    "data": [{"db_name": "MicroMsg.db", "handle": 2}],
                },
                {"result": "OK", "data": [["count(*)"], ["5560"]]},
            ]
        )
        with patch.object(api, "post", side_effect=lambda *args, **kwargs: next(responses)) as post, patch.object(
            api, "InvalidateDatabaseHandles"
        ):
            response = api.QueryDatabase(
                db_name="MicroMsg.db", db_handle=1, sql="select count(*) from Contact"
            )

        self.assertEqual(response["data"][1][0], "5560")
        query_calls = [call for call in post.call_args_list if call.args[0] == 34]
        self.assertEqual(len(query_calls), 2)
        self.assertEqual(query_calls[-1].args[1].db_handle, "2")

    def test_normal_empty_result_does_not_retry(self):
        api = Api()
        with patch.object(api, "post", return_value={"result": "OK", "data": []}) as post:
            response = api.QueryDatabase(
                db_name="MicroMsg.db", db_handle=1, sql="select * from Contact where 0"
            )

        self.assertEqual(response, {"result": "OK", "data": []})
        self.assertEqual(post.call_count, 1)

    def test_named_handle_error_remains_explicit_when_refresh_is_unavailable(self):
        api = Api()
        responses = iter(
            [
                {
                    "result": "ERROR",
                    "err_msg": "database handle unavailable",
                    "data": [],
                },
                {"result": "ERROR", "err_msg": "database handles unavailable", "data": []},
            ]
        )
        with patch.object(api, "post", side_effect=lambda *args, **kwargs: next(responses)) as post, patch.object(
            api, "InvalidateDatabaseHandles"
        ):
            response = api.QueryDatabase(db_name="MicroMsg.db", db_handle=1, sql="select 1")

        self.assertEqual(response["result"], "ERROR")
        self.assertEqual(response["err_msg"], "database handle unavailable")
        self.assertEqual(post.call_count, 2)

    def test_unavailable_database_handle_returns_zero(self):
        api = Api()
        api.GetDatabaseHandles = lambda: {"data": []}

        self.assertEqual(api.GetDBHandle("MicroMsg.db"), 0)

    def test_invalidate_db_handles_notifies_native(self):
        api = Api()
        api.db_handle = {"MicroMsg.db": 1}
        with patch.object(api, "post", return_value={"result": "OK"}) as post:
            api.invalidate_db_handles()

        self.assertEqual(api.db_handle, {})
        called_types = [call.args[0] for call in post.call_args_list]
        self.assertIn(WECHAT_DATABASE_INVALIDATE_HANDLES, called_types)


if __name__ == "__main__":
    unittest.main()
