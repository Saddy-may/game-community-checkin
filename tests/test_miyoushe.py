"""Offline Star Rail protocol checks; no real cookies or network requests."""
from __future__ import annotations

import copy
from pathlib import Path
import sys
import unittest
from urllib.parse import urlparse

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from checkin_core import NeedLoginError, RunContext
from adapters.miyoushe import StarRailModule


class Reply:
    def __init__(self, body, status_code=200):
        self.body, self.status_code = body, status_code

    def json(self):
        return copy.deepcopy(self.body)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("offline HTTP error")


class Session:
    def __init__(self, mode="success", role_count=1):
        self.mode = mode
        self.roles = [{"region": "prod_gf_cn", "game_uid": str(100 + n), "nickname": f"测试{n}"}
                      for n in range(role_count)]
        self.signed = set()
        self.calls = []
        self.sign_submissions = 0

    def request(self, method, url, **kwargs):
        path = urlparse(url).path
        self.calls.append((method, path, kwargs))
        if path.endswith("getUserGameRolesByCookie"):
            assert kwargs["params"]["game_biz"] == "hkrpg_cn"
            return Reply({"retcode": 0, "data": {"list": self.roles}})
        if path.endswith("/info"):
            uid = kwargs["params"]["uid"]
            if self.mode == "malformed_state":
                return Reply({"retcode": 0, "data": {}})
            if self.mode == "nonboolean_state":
                return Reply({"retcode": 0, "data": {"is_sign": "false"}})
            return Reply({"retcode": 0, "data": {"is_sign": uid in self.signed,
                                                  "first_bind": self.mode == "first_bind"}})
        if path.endswith("/sign"):
            self.sign_submissions += 1
            uid = kwargs["json"]["uid"]
            if self.mode == "captcha":
                return Reply({"retcode": 0, "data": {"success": 1, "gt": "challenge-test", "challenge": "offline"}})
            if self.mode == "timeout_before_commit":
                raise requests.Timeout("offline response not received")
            if self.mode == "partial" and uid == "101":
                return Reply({"retcode": -9999, "message": "test failure", "data": {}})
            if self.mode == "expired":
                return Reply({"retcode": -100, "message": "please login", "data": {}})
            self.signed.add(uid)
            if self.mode == "timeout_after_commit":
                raise requests.Timeout("offline response lost after commit")
            return Reply({"retcode": 0, "data": {"success": 0}})
        raise AssertionError(path)


def context(session, cookies=None):
    return RunContext("starrail", {"cookies": cookies or {"cookie_token_v2": "offline-token", "ltuid_v2": "123"}},
                      {}, session=session)


class StarRailProtocolTests(unittest.TestCase):
    def test_captcha_requests_human_input_and_does_not_claim_success(self):
        session = Session("captcha")
        with self.assertRaises(NeedLoginError):
            StarRailModule().run(context(session))
        self.assertEqual(session.sign_submissions, 1)
        self.assertFalse(session.signed)

    def test_timeout_after_server_commit_is_confirmed_without_resubmission(self):
        session = Session("timeout_after_commit")
        result = StarRailModule().run(context(session))
        self.assertEqual(result.status, "success")
        self.assertEqual(session.sign_submissions, 1)

    def test_timeout_without_confirmation_is_an_error_without_resubmission(self):
        session = Session("timeout_before_commit")
        result = StarRailModule().run(context(session))
        self.assertEqual(result.status, "error")
        self.assertEqual(session.sign_submissions, 1)

    def test_one_role_success_does_not_hide_another_failure(self):
        session = Session("partial", role_count=2)
        result = StarRailModule().run(context(session))
        self.assertEqual(result.status, "error")
        self.assertEqual(session.sign_submissions, 2)
        self.assertEqual(len(session.signed), 1)
        self.assertEqual(len(result.details), 2)

    def test_first_binding_requires_manual_official_action(self):
        session = Session("first_bind")
        with self.assertRaises(NeedLoginError):
            StarRailModule().run(context(session))
        self.assertEqual(session.sign_submissions, 0)

    def test_validate_only_reads_roles_and_actual_sign_state(self):
        session = Session(role_count=2)
        result = StarRailModule().validate(context(session))
        self.assertEqual(result.status, "success")
        self.assertEqual(session.sign_submissions, 0)
        self.assertEqual(len([x for x in session.calls if x[1].endswith("/info")]), 2)

    def test_community_only_cookie_cannot_be_marked_ready_for_game_signin(self):
        with self.assertRaises(NeedLoginError):
            StarRailModule().validate(context(Session(), {"ltoken_v2": "offline-community-only"}))

    def test_missing_sign_state_cannot_validate_as_ready(self):
        session = Session("malformed_state")
        try:
            result = StarRailModule().validate(context(session))
        except (RuntimeError, ValueError, KeyError):
            return
        self.assertFalse(result.ok, "A missing is_sign field must not validate as a ready session")

    def test_nonboolean_sign_state_cannot_report_already_signed(self):
        result = StarRailModule().run(context(Session("nonboolean_state")))
        self.assertFalse(result.ok, "String 'false' must not count as an already-signed state")


if __name__ == "__main__":
    unittest.main()
