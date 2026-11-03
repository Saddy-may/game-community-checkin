"""Offline protocol tests. Never connect to game services or use real credentials."""
from __future__ import annotations

import copy
from pathlib import Path
import sys
import unittest
from urllib.parse import urlparse

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from checkin_core import NeedLoginError, RunContext
from adapters.gf2 import GF2Adapter
from adapters.kuro import KuroAdapter


class Reply:
    status_code = 200

    def __init__(self, body, status_code=200):
        self.body, self.status_code = body, status_code

    def json(self):
        return copy.deepcopy(self.body)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("HTTP error")


class GF2Session:
    def __init__(self):
        self.signed = False
        self.score = 200
        self.views, self.likes, self.shares = set(), {"1"}, set()
        self.tasks = True
        self.unknown_task = False
        self.exchanged = 0
        self.exchange_submissions = 0
        self.exchange_timeout = None
        self.calls = []
        self.auth_code = None

    def request(self, method, url, **kwargs):
        path = urlparse(url).path
        self.calls.append((method, path, kwargs))
        if self.auth_code is not None:
            return Reply({"Code": self.auth_code, "Message": "expired", "data": {}})
        data = {}
        if path == "/community/member/info":
            data = {"user": {"game_uid": 12345, "game_nick_name": "测试角色", "score": self.score}}
        elif path == "/community/task/get_current_sign_in_status":
            data = {"has_sign_in": self.signed}
        elif path == "/community/task/sign_in":
            self.signed = True
            self.score += 40
        elif path == "/community/task/get_current_task_list":
            data = {"daily_task": [
                {"task_name": "浏览帖子", "complete_count": len(self.views), "max_complete_count": 3},
                {"task_name": "点赞帖子", "complete_count": max(0, len(self.likes) - 1), "max_complete_count": 3},
                {"task_name": "分享帖子", "complete_count": len(self.shares), "max_complete_count": 1},
            ] if self.tasks else []}
            if self.unknown_task:
                data["daily_task"].append({"task_name": "新的每日任务", "complete_count": 0, "max_complete_count": 1})
        elif path == "/community/topic/list":
            data = {"list": [{"topic_id": n, "status": 0} for n in range(1, 6)]}
        elif path.startswith("/community/topic/like/"):
            tid = path.rsplit("/", 1)[1]
            if tid in self.likes:
                self.likes.remove(tid)
            else:
                self.likes.add(tid)
            data = None  # Official like/share responses can be null.
        elif path.startswith("/community/topic/share/"):
            self.shares.add(path.rsplit("/", 1)[1])
            data = None
        elif path.startswith("/community/topic/"):
            tid = path.rsplit("/", 1)[1]
            self.views.add(tid)
            data = {"topic": {"is_like": tid in self.likes}}
        elif path == "/community/item/exchange_list":
            data = {"list": [{"exchange_id": 1, "item_name": "情报拼图", "exchange_count": self.exchanged,
                              "max_exchange_count": 1, "use_score": 30, "cycle": "day"}]}
        elif path == "/community/item/exchange":
            self.exchange_submissions += 1
            if self.exchange_timeout == "before":
                raise requests.Timeout("request outcome unknown")
            self.exchanged += 1
            self.score -= 30
            if self.exchange_timeout == "after":
                raise requests.Timeout("response lost after server committed")
        else:
            raise AssertionError(f"Unexpected request {method} {path}")
        return Reply({"Code": 0, "Message": "OK", "data": data})


class KuroSession:
    def __init__(self, results=None):
        self.calls = []
        self.results = results or {"wuwa1": 200, "wuwa2": 1511}
        self.roles = [{"gameId": 2, "roleId": "pgr", "serverId": "pgr-server"},
                      {"gameId": 3, "roleId": "wuwa1", "serverId": "wuwa-server", "roleName": "一号"},
                      {"gameId": "3", "roleId": "wuwa2", "serverId": "wuwa-server", "roleName": "二号"}]
        self.auth_code = None

    def request(self, method, url, **kwargs):
        path = urlparse(url).path
        self.calls.append((method, path, kwargs))
        if self.auth_code is not None:
            return Reply({"code": self.auth_code, "msg": "expired"})
        if path == "/user/mineV2":
            return Reply({"code": 200, "data": {"mine": {"userId": 99}}})
        if path == "/user/role/findRoleList":
            assert kwargs["data"] == {"gameId": "3"}
            return Reply({"code": 200, "data": self.roles})
        if path == "/encourage/signIn/v2":
            role_id = kwargs["data"]["roleId"]
            assert kwargs["data"]["gameId"] == "3"
            return Reply({"code": self.results[role_id], "msg": "test result"})
        raise AssertionError(f"Unexpected request {method} {path}")


def context(module_id, session, options=None, credential=None):
    return RunContext(module_id, credential or {"token": "offline-test-token"},
                      {"action_delay": 0, **(options or {})}, session=session)


class GF2ProtocolTests(unittest.TestCase):
    def test_validate_only_reads_identity_and_refuses_wrong_game_role(self):
        session = GF2Session()
        ctx = context("gf2", session)
        result = GF2Adapter().validate(ctx)
        self.assertEqual(result.status, "success")
        self.assertEqual(ctx.credential["game_uid"], 12345)
        self.assertEqual([call[1] for call in session.calls], ["/community/member/info"])
        wrong = context("gf2", session, credential={"token": "offline", "game_uid": "999"})
        self.assertEqual(GF2Adapter().validate(wrong).status, "error")
        self.assertEqual(session.exchange_submissions, 0)
        self.assertFalse(session.signed)

    def test_daily_tasks_verify_counters_and_never_unlike_existing_post(self):
        session = GF2Session()
        result = GF2Adapter().run(context("gf2", session, {"exchange": False}))
        self.assertEqual(result.status, "success", result)
        self.assertGreaterEqual(len(session.views), 3)
        self.assertEqual(len(session.likes), 4)
        self.assertEqual(len(session.shares), 1)
        self.assertIn("1", session.likes)
        self.assertFalse(any(call[1] == "/community/topic/like/1" for call in session.calls))
        self.assertTrue(session.signed)

    def test_unrecognized_daily_task_is_not_reported_as_complete(self):
        session = GF2Session()
        session.tasks, session.unknown_task = False, True
        result = GF2Adapter().run(context("gf2", session, {"exchange": False}))
        self.assertEqual(result.status, "error")
        self.assertTrue(any("新的每日任务" in detail for detail in result.details))

    def test_exchange_timeout_after_commit_is_reconciled_without_repeat(self):
        session = GF2Session()
        session.exchange_timeout = "after"
        result = GF2Adapter().run(context("gf2", session, {"daily_tasks": False}))
        self.assertEqual(result.status, "success", result)
        self.assertEqual(session.exchange_submissions, 1)
        self.assertEqual(session.exchanged, 1)

    def test_unconfirmed_exchange_timeout_stops_without_retry(self):
        session = GF2Session()
        session.exchange_timeout = "before"
        result = GF2Adapter().run(context("gf2", session, {"daily_tasks": False}))
        self.assertEqual(result.status, "error")
        self.assertEqual(session.exchange_submissions, 1)
        self.assertEqual(session.exchanged, 0)
        self.assertIn("避免重复", result.message)

    def test_insufficient_points_do_not_submit_exchange(self):
        session = GF2Session()
        session.score, session.signed = 0, True
        result = GF2Adapter().run(context("gf2", session, {"daily_tasks": False}))
        self.assertEqual(result.status, "already_signed")
        self.assertEqual(session.exchange_submissions, 0)

    def test_expired_community_session_requires_login(self):
        session = GF2Session()
        session.auth_code = 10004
        with self.assertRaises(NeedLoginError):
            GF2Adapter().run(context("gf2", session))

    def test_daily_exchange_limit_is_applied_to_remote_cycle_count(self):
        session = GF2Session()
        result = GF2Adapter().run(context("gf2", session, {
            "daily_tasks": False, "exchange_item_daily_limits": {"1": 0}}))
        self.assertEqual(result.status, "success")
        self.assertEqual(session.exchange_submissions, 0)


class KuroProtocolTests(unittest.TestCase):
    def test_filters_other_game_and_processes_all_wuwa_roles(self):
        session = KuroSession()
        result = KuroAdapter().run(context("wuwa", session))
        self.assertEqual(result.status, "success")
        submissions = [x[2]["data"] for x in session.calls if x[1] == "/encourage/signIn/v2"]
        self.assertEqual({x["roleId"] for x in submissions}, {"wuwa1", "wuwa2"})
        self.assertEqual(len(result.details), 2)

    def test_one_success_does_not_mask_another_role_failure(self):
        session = KuroSession({"wuwa1": 200, "wuwa2": 500})
        result = KuroAdapter().run(context("wuwa", session))
        self.assertEqual(result.status, "error")
        self.assertIn("1/2", result.message)
        self.assertEqual(len(result.details), 2)

    def test_all_already_signed_is_distinct_from_new_success(self):
        session = KuroSession({"wuwa1": 1511, "wuwa2": 1511})
        self.assertEqual(KuroAdapter().run(context("wuwa", session)).status, "already_signed")

    def test_validate_does_not_submit_any_checkin(self):
        session = KuroSession()
        result = KuroAdapter().validate(context("wuwa", session))
        self.assertEqual(result.status, "success")
        self.assertFalse(any("signIn" in call[1] for call in session.calls))

    def test_current_web_identity_uses_user_id_and_captured_device_headers(self):
        session = KuroSession()
        ctx = context("wuwa", session, credential={"token": "offline-web-token", "user_id": "99",
                      "devcode": "offline-device", "distinct_id": "offline-distinct",
                      "source": "h5", "api_version": "3.3.2"})
        self.assertEqual(KuroAdapter().validate(ctx).status, "success")
        mine = session.calls[0][2]
        self.assertEqual(mine["data"], {"viewUserId": "99"})
        self.assertEqual(mine["headers"]["source"], "h5")
        self.assertEqual(mine["headers"]["version"], "3.3.2")
        self.assertEqual(mine["headers"]["devcode"], "offline-device")
        self.assertEqual(KuroAdapter.site, "https://www.kurobbs.com/mc/home/9")

    def test_expired_kuro_session_requires_login(self):
        session = KuroSession()
        session.auth_code = 220
        with self.assertRaises(NeedLoginError):
            KuroAdapter().run(context("wuwa", session))

    def test_missing_selected_role_is_an_error_before_any_signin(self):
        session = KuroSession()
        result = KuroAdapter().run(context("wuwa", session, {"role_ids": ["missing"]}))
        self.assertEqual(result.status, "error")
        self.assertFalse(any("signIn" in call[1] for call in session.calls))


if __name__ == "__main__":
    unittest.main()
