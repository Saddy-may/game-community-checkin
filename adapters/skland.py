"""Local Skland game attendance. No account secrets are logged.

Protocol reviewed against FCAnon89/SklandAutoSign/SklandClient.cs and
ErikaCarnea/SklandCheckin/internal/api/attendance.go (2026-11-03).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode, urlsplit

import requests

from checkin_core import NeedLoginError, RunContext, RunResult


BASE = "https://zonai.skland.com"
GRANT_URL = "https://as.hypergryph.com/user/oauth2/v2/grant"
APP_CODE = "4ca99fa6b56cc2ba"
UA = "Skland/1.0.1 (com.hypergryph.skland; build:100001014; Android 31; ) Okhttp/4.11.0"
CST = timezone(timedelta(hours=8))


def normalize_token(value) -> str:
    if isinstance(value, dict):
        data = value.get("data", value)
        value = data.get("content", data.get("token", "")) if isinstance(data, dict) else ""
    elif isinstance(value, str):
        value = value.strip()
        if value.startswith("{"):
            try:
                return normalize_token(json.loads(value))
            except (ValueError, TypeError):
                raise NeedLoginError("森空岛登录信息格式有误，请重新登录") from None
    token = str(value or "").strip().strip('"')
    if not token:
        raise NeedLoginError("请先登录森空岛")
    return token


def signed_headers(cred: str, sign_token: str, url: str, body: str = "", *,
                   device_id: str = "", timestamp: int | None = None) -> dict[str, str]:
    stamp = str(int(time.time()) if timestamp is None else timestamp)
    selected = {"platform": "3", "timestamp": stamp, "dId": device_id, "vName": "1.0.0"}
    parts = urlsplit(url)
    content = parts.query if parts.query else body
    source = parts.path + content + stamp + json.dumps(selected, separators=(",", ":"), ensure_ascii=False)
    digest = hmac.new(sign_token.encode(), source.encode(), hashlib.sha256).hexdigest()
    return {"cred": cred, **selected, "sign": hashlib.md5(digest.encode()).hexdigest(),
            "User-Agent": UA, "Accept": "application/json"}


class SklandClient:
    def __init__(self, ctx: RunContext):
        self.ctx = ctx
        self.token = normalize_token(ctx.credential.get("token", ctx.credential.get("content")))
        self.device_id = str(ctx.credential.get("dId", ""))
        self.cred = ""
        self.sign_token = ""

    def _safe_message(self, value) -> str:
        message = str(value or "服务端未给出原因")
        for secret in (self.token, self.cred, self.sign_token):
            if secret:
                message = message.replace(secret, "[已隐藏]")
        return message[:180]

    def _http(self, method: str, url: str, *, headers=None, body=None) -> dict:
        # Only read-only requests are retried. A timed-out POST may have succeeded.
        for attempt in range(2 if method == "GET" else 1):
            try:
                response = self.ctx.session.request(method, url, headers=headers,
                    data=body, timeout=20, allow_redirects=False)
            except requests.RequestException:
                if method == "GET" and attempt == 0:
                    continue
                raise RuntimeError("网络请求未完成，请检查网络后重试") from None
            if response.status_code in (401, 403):
                raise NeedLoginError("森空岛需要重新登录或人工验证")
            if not 200 <= response.status_code < 300:
                error = RuntimeError(f"森空岛服务返回 HTTP {response.status_code}")
                error.http_status = response.status_code
                raise error
            try:
                payload = response.json()
            except (ValueError, TypeError):
                raise RuntimeError("森空岛返回了无法识别的内容，请稍后重试") from None
            if not isinstance(payload, dict):
                raise RuntimeError("森空岛响应格式有变化，请更新适配器")
            return payload
        raise RuntimeError("网络请求未完成")

    def _check(self, payload: dict, operation: str) -> dict:
        if payload.get("code", payload.get("status")) == 0:
            data = payload.get("data")
            return data if isinstance(data, dict) else {}
        message = self._safe_message(payload.get("message", payload.get("msg")))
        if any(word in message.lower() for word in ("登录", "失效", "过期", "未授权", "token", "cred", "验证码", "设备验证")):
            raise NeedLoginError("森空岛登录失效或需要人工验证，请重新登录")
        raise RuntimeError(f"{operation}失败：{message}（代码 {payload.get('code', payload.get('status', '未知'))}）")

    def login(self):
        common = {"Content-Type": "application/json", "User-Agent": UA}
        if self.device_id:
            common["dId"] = self.device_id
        data = self._check(self._http("POST", GRANT_URL, headers=common,
            body=json.dumps({"appCode": APP_CODE, "token": self.token, "type": 0}, separators=(",", ":"))), "登录授权")
        if not data.get("code"):
            raise NeedLoginError("森空岛授权响应缺少凭据，请重新登录")
        data = self._check(self._http("POST", BASE + "/api/v1/user/auth/generate_cred_by_code",
            headers=common, body=json.dumps({"code": data["code"], "kind": 1}, separators=(",", ":"))), "获取签到授权")
        if not data.get("cred") or not data.get("token"):
            raise NeedLoginError("森空岛没有返回完整的签到授权，请重新登录")
        self.cred, self.sign_token = str(data["cred"]), str(data["token"])

    def signed(self, method: str, path: str, body: str = "", extra=None) -> dict:
        url = BASE + path
        headers = signed_headers(self.cred, self.sign_token, url, body, device_id=self.device_id)
        if method == "POST":
            headers["Content-Type"] = "application/json"
        if extra:
            headers.update(extra)
        return self._http(method, url, headers=headers, body=body.encode() if method == "POST" else None)

    def roles(self, game: str) -> list[dict]:
        data = self._check(self.signed("GET", "/api/v1/game/player/binding"), "读取绑定角色")
        apps = data.get("list")
        if not isinstance(apps, list):
            raise RuntimeError("森空岛绑定角色响应格式有变化")
        roles, seen = [], set()
        for app in apps:
            if not isinstance(app, dict) or app.get("appCode") != game:
                continue
            for binding in app.get("bindingList", []):
                if not isinstance(binding, dict):
                    continue
                if game == "arknights":
                    uid, channel = str(binding.get("uid", "")), str(binding.get("channelMasterId", ""))
                    if uid and channel and (uid, channel) not in seen:
                        seen.add((uid, channel))
                        roles.append({"uid": uid, "gameId": channel,
                            "name": str(binding.get("nickName", "明日方舟角色"))})
                else:
                    candidates = list(binding.get("roles") or [])
                    if isinstance(binding.get("defaultRole"), dict):
                        candidates.append(binding["defaultRole"])
                    for role in candidates:
                        if not isinstance(role, dict):
                            continue
                        rid, sid = str(role.get("roleId", "")), str(role.get("serverId", ""))
                        key = (str(binding.get("uid", "")), rid, sid)
                        if rid and sid and key not in seen:
                            seen.add(key)
                            roles.append({"roleId": rid, "serverId": sid,
                                "name": str(role.get("nickname", binding.get("nickName", "终末地角色")))})
        return roles

    def is_signed(self, game: str, role: dict) -> bool:
        if game == "arknights":
            # The read endpoint identifies the game (Arknights=1), not its
            # publishing channel. Bilibili's channelMasterId=2 is not gameId here.
            query = urlencode({"uid": role["uid"], "gameId": "1"})
            data = self._check(self.signed("GET", "/api/v1/game/attendance?" + query), "查询签到状态")
            records = data.get("records")
            if not isinstance(records, list):
                raise RuntimeError("签到状态没有返回记录，无法确认结果")
            today = datetime.now(CST).date()
            for record in records:
                try:
                    stamp = float(record.get("ts"))
                    if stamp > 10**11:
                        stamp /= 1000
                    if datetime.fromtimestamp(stamp, CST).date() == today:
                        return True
                except (TypeError, ValueError, OSError, OverflowError, AttributeError):
                    continue
            return False
        extra = {"sk-game-role": f"3_{role['roleId']}_{role['serverId']}",
                 "origin": "https://game.skland.com", "referer": "https://game.skland.com/"}
        data = self._check(self.signed("GET", "/web/v1/game/endfield/attendance", extra=extra), "查询签到状态")
        # Accept explicit current-day flags only; cumulative days do not prove today.
        for key in ("hasToday", "todaySign", "todaySigned", "hasSignedInToday", "isTodaySigned"):
            if isinstance(data.get(key), bool):
                return data[key]
        raise RuntimeError("终末地未返回可确认的当日状态，请在官方页面核对")

    def sign(self, game: str, role: dict) -> tuple[str, str]:
        if game == "arknights":
            body = json.dumps({"uid": role["uid"], "gameId": role["gameId"]}, separators=(",", ":"))
            payload = self.signed("POST", "/api/v1/game/attendance", body)
        else:
            extra = {"sk-game-role": f"3_{role['roleId']}_{role['serverId']}",
                     "origin": "https://game.skland.com", "referer": "https://game.skland.com/"}
            try:
                payload = self.signed("POST", "/web/v1/game/endfield/attendance", "", extra)
            except RuntimeError as exc:
                if getattr(exc, "http_status", None) not in (404, 405):
                    raise
                payload = self.signed("POST", "/api/v1/game/endfield/attendance", "", extra)
        code = payload.get("code")
        if code == 0:
            return "success", "签到成功"
        if code == 10001:
            return "already_signed", "今日已签到"
        self._check(payload, "签到")
        raise RuntimeError("签到没有返回明确结果")


class _SklandGame:
    platform = "skland"
    site = "https://www.skland.com/"

    def validate(self, ctx: RunContext) -> RunResult:
        client = SklandClient(ctx)
        client.login()
        roles = client.roles(self.game)
        if not roles:
            return RunResult("error", f"未找到绑定的{self.name}角色，请先在森空岛绑定", [])
        return RunResult("success", f"登录有效，找到 {len(roles)} 个角色", [role["name"] for role in roles])

    def run(self, ctx: RunContext) -> RunResult:
        client = SklandClient(ctx)
        client.login()
        roles = client.roles(self.game)
        if not roles:
            return RunResult("error", "未找到已绑定角色，请先在森空岛绑定", [])
        outcomes, details = [], []
        for role in roles:
            label = role["name"]
            try:
                try:
                    signed = client.is_signed(self.game, role)
                except NeedLoginError:
                    raise
                except RuntimeError:
                    signed = False  # Unknown status is never treated as success.
                if signed:
                    status, message = "already_signed", "今日已签到"
                else:
                    try:
                        status, message = client.sign(self.game, role)
                    except NeedLoginError:
                        raise
                    except RuntimeError:
                        # Do not repeat a possibly committed POST. Check read-only state.
                        try:
                            confirmed = client.is_signed(self.game, role)
                        except NeedLoginError:
                            raise
                        except RuntimeError:
                            confirmed = False
                        if confirmed:
                            status, message = "success", "已通过签到记录确认成功"
                        else:
                            status, message = "error", "签到结果未能确认，请稍后重试或在官方页面核对"
                outcomes.append(status)
                details.append(f"{label}：{message}")
            except NeedLoginError:
                outcomes.append("needs_login")
                details.append(f"{label}：需要重新登录或人工验证")
            except Exception:
                outcomes.append("error")
                details.append(f"{label}：请求失败，请检查网络或更新适配器")
            ctx.log(details[-1])
        if "needs_login" in outcomes:
            return RunResult("needs_login", "部分角色需要重新登录或人工验证", details)
        if "error" in outcomes:
            return RunResult("error", "部分角色签到失败或结果未确认", details)
        status = "already_signed" if all(x == "already_signed" for x in outcomes) else "success"
        return RunResult(status, f"{len(roles)} 个角色均已完成今日签到", details)


class SklandArknights(_SklandGame):
    id = "skland_arknights"
    name = "明日方舟"
    game = "arknights"


class SklandEndfield(_SklandGame):
    id = "skland_endfield"
    name = "明日方舟：终末地"
    game = "endfield"


MODULES = [SklandArknights(), SklandEndfield()]
