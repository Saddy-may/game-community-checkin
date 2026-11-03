"""Offline protocol and error-handling checks; never signs into a real account."""
from datetime import datetime
import json
import unittest
from urllib.parse import parse_qs

import requests

from checkin_core import NeedLoginError, RunContext
from adapters import skland, tajiduo


class Response:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status

    def json(self):
        return self.payload


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if not self.responses:
            raise AssertionError("Unexpected request: " + url)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item if isinstance(item, Response) else Response(item)


def context(game, responses, credential=None, save=None):
    return RunContext(game, credential or {"token": "test-token"}, {},
                      save_credential=save or (lambda value: None), session=Session(responses))


def login_responses(bindings):
    return [{"status": 0, "data": {"code": "code"}},
            {"code": 0, "data": {"cred": "cred", "token": "sign-key"}},
            {"code": 0, "data": {"list": bindings}}]


class SklandTests(unittest.TestCase):
    def test_get_signature_matches_independent_node_vector(self):
        headers = skland.signed_headers("cred", "key", skland.BASE + "/api/v1/game/attendance?uid=123&gameId=1", timestamp=1700000000)
        self.assertEqual(headers["sign"], "af3859f86b336e652d850c2c29d36538")

    def test_token_import_from_official_json(self):
        self.assertEqual(skland.normalize_token('{"data":{"content":"test-token"}}'), "test-token")
        with self.assertRaises(NeedLoginError):
            skland.normalize_token("")

    def test_endfield_roles_deduplicate_default_without_losing_other_roles(self):
        first = {"roleId": "r1", "serverId": "s1", "nickname": "One"}
        second = {"roleId": "r2", "serverId": "s2", "nickname": "Two"}
        ctx = context("skland_endfield", login_responses([
            {"appCode": "arknights", "bindingList": [{"uid": "ak", "channelMasterId": "1"}]},
            {"appCode": "endfield", "bindingList": [{"uid": "a", "roles": [first, second], "defaultRole": first}]}]))
        result = skland.SklandEndfield().validate(ctx)
        self.assertEqual(result.status, "success")
        self.assertEqual(len(result.details), 2)
        self.assertFalse(any(c[0] == "POST" and c[1].endswith("attendance") for c in ctx.session.calls))

    def test_partial_failure_is_not_reported_as_success(self):
        roles = [{"uid": "one", "channelMasterId": "1", "nickName": "One"},
                 {"uid": "two", "channelMasterId": "1", "nickName": "Two"}]
        responses = login_responses([{"appCode": "arknights", "bindingList": roles}])
        responses += [{"code": 0, "data": {"records": []}}, {"code": 0},
                      {"code": 0, "data": {"records": []}}, requests.Timeout(),
                      {"code": 0, "data": {"records": []}}]
        ctx = context("skland_arknights", responses)
        result = skland.SklandArknights().run(ctx)
        self.assertEqual(result.status, "error")
        self.assertEqual(len(result.details), 2)
        posts = [c for c in ctx.session.calls if c[0] == "POST" and c[1].endswith("attendance")]
        self.assertEqual(len(posts), 2)

    def test_post_timeout_is_confirmed_read_only_without_reposting(self):
        midnight = int(datetime.now(skland.CST).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        responses = login_responses([{"appCode": "arknights", "bindingList": [{"uid": "one", "channelMasterId": "1"}]}])
        responses += [{"code": 0, "data": {"records": []}}, requests.Timeout(),
                      {"code": 0, "data": {"records": [{"ts": str(midnight)}]}}]
        ctx = context("skland_arknights", responses)
        self.assertEqual(skland.SklandArknights().run(ctx).status, "success")
        self.assertEqual(len([c for c in ctx.session.calls if c[0] == "POST" and c[1].endswith("attendance")]), 1)

    def test_endfield_signs_empty_body_with_specific_role(self):
        ctx = context("skland_endfield", [{"code": 0}])
        client = skland.SklandClient(ctx)
        client.cred, client.sign_token = "cred", "key"
        self.assertEqual(client.sign("endfield", {"roleId": "r1", "serverId": "s1"})[0], "success")
        kwargs = ctx.session.calls[0][2]
        self.assertEqual(kwargs["data"], b"")
        self.assertEqual(kwargs["headers"]["sk-game-role"], "3_r1_s1")

    def test_endfield_has_today_is_checked_without_posting(self):
        role = {"roleId": "r1", "serverId": "s1", "nickname": "One"}
        ctx = context("skland_endfield", login_responses([
            {"appCode": "endfield", "bindingList": [{"uid": "a", "roles": [role]}]}]) +
            [{"code": 0, "data": {"hasToday": True, "calendar": [], "currentTs": "123"}}])
        result = skland.SklandEndfield().run(ctx)
        self.assertEqual(result.status, "already_signed")
        self.assertFalse(any(c[0] == "POST" and c[1].endswith("attendance") for c in ctx.session.calls))

    def test_endfield_has_today_requires_boolean(self):
        ctx = context("skland_endfield", [{"code": 0, "data": {"hasToday": "true"}}])
        client = skland.SklandClient(ctx)
        client.cred, client.sign_token = "cred", "key"
        with self.assertRaises(RuntimeError):
            client.is_signed("endfield", {"roleId": "r1", "serverId": "s1"})

    def test_bilibili_attendance_query_uses_game_id_one(self):
        ctx = context("skland_arknights", [{"code": 0, "data": {"records": []}}])
        client = skland.SklandClient(ctx)
        client.cred, client.sign_token = "cred", "key"
        self.assertFalse(client.is_signed("arknights", {"uid": "bili", "gameId": "2"}))
        self.assertTrue(ctx.session.calls[0][1].endswith("uid=bili&gameId=1"))


class TajiduoTests(unittest.TestCase):
    credential = {"accessToken": "access", "refreshToken": "refresh", "uid": "u1", "deviceId": "device"}

    def test_ds_matches_independent_node_vector(self):
        self.assertEqual(tajiduo.make_ds(1700000000, "abcdefgh"), "1700000000,abcdefgh,14be174b1a01a477d7f70ef3b225beb4")

    def test_aes_transport_matches_independent_node_vector(self):
        self.assertEqual(tajiduo._aes_encode("13800000000"), "IqfquRou563hM4IuwWbe4Q==")

    def test_only_nte_roles_selected(self):
        ctx = context("tajiduo_nte", [{"code": 0, "data": {"roles": [
            {"roleId": "other", "gameId": "1256"},
            {"roleId": "nte", "gameId": "1289", "roleName": "NTE"}]}}], dict(self.credential))
        result = tajiduo.TajiduoNTE().validate(ctx)
        self.assertEqual(result.details, ["NTE"])
        self.assertEqual(ctx.session.calls[0][2]["params"], {"gameId": "1289"})

    def test_default_role_state_does_not_skip_other_roles(self):
        state = {"todaySign": True, "days": 1}
        self.assertFalse(tajiduo.TajiduoClient.confirms_role_today(state, {"roleId": "two"}, 2))
        self.assertTrue(tajiduo.TajiduoClient.confirms_role_today({**state, "roleId": "two"}, {"roleId": "two"}, 2))
        self.assertFalse(tajiduo.TajiduoClient.confirms_role_today({"days": 5}, {"roleId": "two"}, 1))

    def test_expired_access_refreshes_once_and_persists_rotation(self):
        saved = []
        ctx = context("tajiduo_nte", [Response({}, 401),
            {"code": 0, "data": {"accessToken": "access-new", "refreshToken": "refresh-new", "uid": "u1"}},
            {"code": 0, "data": {"roles": [{"roleId": "nte"}]}}], dict(self.credential), saved.append)
        self.assertTrue(tajiduo.TajiduoNTE().validate(ctx).ok)
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["refreshToken"], "refresh-new")
        self.assertEqual(ctx.session.calls[-1][2]["headers"]["Authorization"], "access-new")

    def test_invalid_refresh_requests_login_without_loop(self):
        ctx = context("tajiduo_nte", [Response({}, 401), {"code": 9, "msg": "失效"}], dict(self.credential))
        with self.assertRaises(NeedLoginError):
            tajiduo.TajiduoNTE().validate(ctx)
        self.assertEqual(len(ctx.session.calls), 2)

    def test_timeout_does_not_repeat_sign_post_or_report_success(self):
        ctx = context("tajiduo_nte", [{"code": 0, "data": {"roles": [{"roleId": "nte"}]}},
            {"code": 0, "data": {"todaySign": False}}, requests.Timeout(),
            {"code": 0, "data": {"todaySign": False}}], dict(self.credential))
        self.assertEqual(tajiduo.TajiduoNTE().run(ctx).status, "error")
        self.assertEqual(len([c for c in ctx.session.calls if c[0] == "POST"]), 1)

    def test_sms_full_protocol_returns_only_required_session_fields(self):
        session = Session([{"code": 0}, {"code": 0},
            {"code": 0, "result": {"token": "laohu-token", "userId": 12345678901234567890}},
            {"code": 0, "data": {"accessToken": "a", "refreshToken": "r", "uid": 999}}])
        tajiduo.send_sms("13800000000", "device", session)
        account = tajiduo.login_sms("13800000000", "123456", "device", session)
        self.assertEqual(account, {"accessToken": "a", "refreshToken": "r", "uid": "999", "deviceId": "device"})
        form = parse_qs(session.calls[2][2]["data"])
        self.assertNotEqual(form["cellphone"], ["13800000000"])
        self.assertNotEqual(form["captcha"], ["123456"])
        self.assertEqual(parse_qs(session.calls[3][2]["data"])["userIdentity"], ["12345678901234567890"])
        self.assertFalse(any("phone" in key.lower() or "token" == key.lower() for key in account))


if __name__ == "__main__":
    unittest.main()
