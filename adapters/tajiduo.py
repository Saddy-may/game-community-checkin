"""Tajiduo NTE-only attendance and user-initiated SMS login.

Protocol reviewed against zzstar101/taygedo-auto-attendance src/taygedo
and Candy-QAQ/NTE-Auto-Sign (2026-11-03). No forum/like/share/cloud tasks.
"""
from __future__ import annotations

import base64
import hashlib
import re
import secrets
import string
import time
from urllib.parse import urlencode

import requests

from checkin_core import NeedLoginError, RunContext, RunResult


BASE = "https://bbs-api.tajiduo.com"
LAOHU_BASE = "https://user.laohu.com"
GAME_ID = "1289"
APP_VERSION = "1.2.5"
DS_SECRET = "pUds3dfMkl"
LAOHU_SECRET = "89155cc4e8634ec5b1b6364013b23e3e"
LAOHU_UA = "LaohuSDK/4.327.0 (android os 14;mobile  manufacturer Google; model Pixel 6) "
H5_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Tajiduo/1.2.2"


def generate_device_id() -> str:
    return secrets.token_hex(16)


def make_ds(timestamp: int | None = None, nonce: str | None = None) -> str:
    stamp = int(time.time()) if timestamp is None else timestamp
    nonce = nonce or "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))
    digest = hashlib.md5(f"{stamp}{nonce}{APP_VERSION}{DS_SECRET}".encode()).hexdigest()
    return f"{stamp},{nonce},{digest}"


def _message(payload: dict) -> str:
    return str(payload.get("message") or payload.get("msg") or "服务端未给出原因")[:180]


def _auth_message(payload: dict) -> bool:
    text = _message(payload).lower()
    return any(x in text for x in ("未登录", "请先登录", "登录过期", "登录失效", "登录已过期", "token", "未授权", "授权失效", "验证码", "人机验证"))


def _http(session, method: str, url: str, *, headers=None, data=None, params=None) -> dict:
    for attempt in range(2 if method == "GET" else 1):
        try:
            response = session.request(method, url, headers=headers, data=data, params=params,
                                       timeout=20, allow_redirects=False)
        except requests.RequestException:
            if method == "GET" and attempt == 0:
                continue
            raise RuntimeError("网络请求未完成，请检查网络后重试") from None
        if response.status_code in (401, 402, 403):
            raise NeedLoginError("塔吉多需要重新登录或人工验证")
        if not 200 <= response.status_code < 300:
            raise RuntimeError(f"塔吉多服务返回 HTTP {response.status_code}")
        try:
            payload = response.json()
        except (ValueError, TypeError):
            raise RuntimeError("塔吉多返回了无法识别的内容，请稍后重试") from None
        if not isinstance(payload, dict):
            raise RuntimeError("塔吉多响应格式有变化，请更新适配器")
        return payload
    raise RuntimeError("网络请求未完成")


def _laohu_params(device_id: str, version_field: str) -> dict[str, str]:
    stamp = int(time.time() * (1000 if version_field == "version" else 1))
    data = {"adm": "", "appId": "10550", "bid": "com.pwrd.htassistant",
            "channelId": "1", "deviceId": device_id, "deviceModel": "Pixel 6",
            "deviceName": "Pixel 6", "deviceSys": "14", "deviceType": "Pixel 6",
            "idfa": "", "sdkVersion": "4.327.0", "t": str(stamp), version_field: "17"}
    data["mac" if version_field == "version" else "imei"] = ""
    return data


def laohu_signed_form(data: dict[str, str], include_empty: bool = True) -> str:
    signature = hashlib.md5(("".join(data[key] for key in sorted(data)) + LAOHU_SECRET).encode()).hexdigest()
    signed = {**data, "sign": signature}
    return urlencode({key: value for key, value in signed.items() if include_empty or value != ""})


def _aes_encode(value: str) -> str:
    # This is the official SDK's transport encoding; local storage uses Windows DPAPI.
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    raw = value.encode()
    amount = 16 - len(raw) % 16
    encryptor = Cipher(algorithms.AES(LAOHU_SECRET[-16:].encode()), modes.ECB()).encryptor()
    return base64.b64encode(encryptor.update(raw + bytes([amount]) * amount) + encryptor.finalize()).decode()


def _check_phone(phone: str):
    if not re.fullmatch(r"1\d{10}", phone):
        raise ValueError("请输入中国大陆 11 位手机号")


def _laohu_post(session, path: str, data: dict, *, include_empty=True) -> dict:
    return _http(session, "POST", LAOHU_BASE + path,
                 headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "User-Agent": LAOHU_UA},
                 data=laohu_signed_form(data, include_empty))


def send_sms(phone: str, device_id: str, session=None) -> None:
    """Send a code only when explicitly invoked by the user-facing login dialog."""
    _check_phone(phone)
    if not device_id:
        raise ValueError("缺少本机登录设备标识")
    session = session or requests.Session()
    payload = _laohu_post(session, "/m/newApi/sendPhoneCaptchaWithOutLogin",
        {**_laohu_params(device_id, "versionCode"), "areaCodeId": "1", "cellphone": phone, "type": "16"},
        include_empty=False)
    if payload.get("code") == 0 or (payload.get("code") == 1 and "短信正在发送" in _message(payload)):
        return
    # Avoid including the raw upstream response: it may echo a phone or session.
    if "验证" in _message(payload) or "频繁" in _message(payload):
        raise NeedLoginError("短信请求需要人工验证或次数过多，请稍后再试或在官方社区登录")
    raise RuntimeError(f"短信发送未被接受（代码 {payload.get('code', '未知')}），请在官方社区核对")


def _session_headers(authorization: str, uid: str, device_id: str) -> dict[str, str]:
    return {"Accept": "application/json, text/plain, */*", "Authorization": authorization,
            "appVersion": APP_VERSION, "platform": "android", "uid": uid,
            "debug-uid": "3", "deviceId": device_id, "ds": make_ds(),
            "Content-Type": "application/x-www-form-urlencoded", "User-Agent": "okhttp/4.12.0"}


def login_sms(phone: str, code: str, device_id: str, session=None) -> dict:
    """Complete the SMS login and return an account dict; never writes plaintext."""
    _check_phone(phone)
    if not re.fullmatch(r"\d{4,8}", code.strip()):
        raise ValueError("请输入收到的短信验证码")
    session = session or requests.Session()
    checked = _laohu_post(session, "/m/newApi/checkPhoneCaptchaWithOutLogin",
        {**_laohu_params(device_id, "versionCode"), "captcha": code.strip(), "cellphone": phone},
        include_empty=False)
    if checked.get("code") != 0:
        raise NeedLoginError("短信验证码无效或已过期，请重新获取")
    payload = _laohu_post(session, "/openApi/sms/new/login",
        {**_laohu_params(device_id, "version"), "areaCodeId": "1",
         "captcha": _aes_encode(code.strip()), "cellphone": _aes_encode(phone), "type": "16"})
    result = payload.get("result")
    if payload.get("code") != 0 or not isinstance(result, dict) or not result.get("token") or result.get("userId") is None:
        raise NeedLoginError("短信登录未完成，请在官方社区完成登录后重试")
    body = {"token": str(result["token"]), "userIdentity": str(result["userId"]), "appId": "10551"}
    payload = _http(session, "POST", BASE + "/usercenter/api/login",
                    headers=_session_headers("", "0", device_id), data=urlencode(body))
    # Upstream's narrow compatibility fallback applies only to an explicit system error.
    if payload.get("code") == 1 and _message(payload) == "系统错误":
        headers = {"authorization": "", "appversion": "1.1.0", "platform": "android",
                   "uid": "10000000", "deviceid": device_id,
                   "Content-Type": "application/x-www-form-urlencoded", "User-Agent": "okhttp/4.12.0"}
        payload = _http(session, "POST", BASE + "/usercenter/api/login", headers=headers, data=urlencode(body))
    data = payload.get("data")
    if payload.get("code") != 0 or not isinstance(data, dict) or not data.get("accessToken") or not data.get("refreshToken") or data.get("uid") is None:
        raise NeedLoginError("塔吉多没有返回完整登录授权，请在官方社区确认后重试")
    return {"accessToken": str(data["accessToken"]), "refreshToken": str(data["refreshToken"]),
            "uid": str(data["uid"]), "deviceId": device_id}


class TajiduoClient:
    def __init__(self, ctx: RunContext):
        self.ctx = ctx
        self.account = dict(ctx.credential)
        if not self.account.get("uid"):
            raise NeedLoginError("请先登录塔吉多")
        if not self.account.get("accessToken") and not self.account.get("refreshToken"):
            raise NeedLoginError("请先登录塔吉多")
        if not self.account.get("deviceId"):
            self.account["deviceId"] = generate_device_id()
            self.ctx.save_credential(dict(self.account))
            self.ctx.credential.update(self.account)
        self.refreshed = False

    def _data(self, payload: dict, operation: str):
        if payload.get("code") == 0:
            return payload.get("data")
        if _auth_message(payload):
            raise NeedLoginError("塔吉多登录已过期或需要人工验证")
        # Only disclose a business code, not arbitrary echoed upstream data.
        raise RuntimeError(f"{operation}未完成（代码 {payload.get('code', '未知')}），请在官方社区核对")

    def refresh(self):
        if self.refreshed or not self.account.get("refreshToken"):
            raise NeedLoginError("塔吉多需要重新登录")
        self.refreshed = True
        payload = _http(self.ctx.session, "POST", BASE + "/usercenter/api/refreshToken",
            headers=_session_headers(str(self.account["refreshToken"]), str(self.account["uid"]), str(self.account["deviceId"])))
        if payload.get("code") != 0:
            raise NeedLoginError("塔吉多登录授权已失效，请重新登录")
        data = self._data(payload, "刷新登录授权")
        if not isinstance(data, dict) or not data.get("accessToken") or not data.get("refreshToken"):
            raise NeedLoginError("塔吉多登录授权已失效，请重新登录")
        self.account.update(accessToken=str(data["accessToken"]), refreshToken=str(data["refreshToken"]))
        if data.get("uid") is not None:
            self.account["uid"] = str(data["uid"])
        self.ctx.save_credential(dict(self.account))
        self.ctx.credential.update(self.account)

    def request(self, method: str, path: str, *, native=False, params=None, data=None):
        if not self.account.get("accessToken"):
            self.refresh()
        for attempt in range(2):
            if native:
                headers = {"Accept": "application/json", "Authorization": str(self.account["accessToken"]),
                           "appversion": APP_VERSION, "platform": "android", "uid": str(self.account["uid"]),
                           "deviceid": str(self.account["deviceId"]), "ds": make_ds(), "User-Agent": "okhttp/4.12.0"}
            else:
                headers = {"Accept": "application/json", "Authorization": str(self.account["accessToken"]),
                           "Origin": "https://webstatic.tajiduo.com", "Referer": "https://webstatic.tajiduo.com/", "User-Agent": H5_UA}
            if data is not None:
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            try:
                payload = _http(self.ctx.session, method, BASE + path, headers=headers,
                                params=params, data=urlencode(data) if data is not None else None)
                # Preserve explicit "already" messages for state verification.
                if payload.get("code") != 0 and _auth_message(payload):
                    raise NeedLoginError("塔吉多登录需要刷新")
                return payload
            except NeedLoginError:
                if attempt == 0 and not self.refreshed:
                    self.refresh()
                    continue
                raise
        raise NeedLoginError("塔吉多需要重新登录")

    def roles(self) -> list[dict]:
        data = self._data(self.request("GET", "/usercenter/api/v2/getGameRoles", native=True,
                                      params={"gameId": GAME_ID}), "读取异环角色")
        if not isinstance(data, dict) or not isinstance(data.get("roles"), list):
            raise RuntimeError("塔吉多角色响应格式有变化，请更新适配器")
        roles, seen = [], set()
        for role in data["roles"]:
            if not isinstance(role, dict) or role.get("roleId") is None:
                continue
            # Never traverse other bound games even if the server returns extra rows.
            if role.get("gameId") is not None and str(role["gameId"]) != GAME_ID:
                continue
            rid = str(role["roleId"])
            if rid and rid not in seen:
                seen.add(rid)
                roles.append({"roleId": rid, "name": str(role.get("roleName") or "异环角色")})
        return roles

    def state(self) -> dict:
        data = self._data(self.request("GET", "/apihub/awapi/signin/state", params={"gameId": GAME_ID}), "查询异环签到状态")
        if not isinstance(data, dict):
            raise RuntimeError("异环签到状态格式有变化")
        return data

    @staticmethod
    def confirms_role_today(state: dict, role: dict, count: int) -> bool:
        if state.get("todaySign") is not True and state.get("todaySign") != 1:
            return False
        # This endpoint may describe the default role. Do not skip all multi-role accounts.
        state_role = state.get("roleId")
        return str(state_role) == role["roleId"] if state_role is not None else count == 1

    def sign(self, role: dict, count: int) -> tuple[str, str]:
        payload = self.request("POST", "/apihub/awapi/sign", data={"roleId": role["roleId"], "gameId": GAME_ID})
        if payload.get("code") == 0:
            return "success", "签到成功"
        message = _message(payload)
        if any(word in message for word in ("已签到", "签到过", "重复签到")):
            if self.confirms_role_today(self.state(), role, count):
                return "already_signed", "今日已签到（已核对服务端状态）"
            raise RuntimeError("服务端提示重复签到，但当日状态未能确认")
        self._data(payload, "异环签到")
        raise RuntimeError("异环签到没有返回明确结果")


class TajiduoNTE:
    id = "tajiduo_nte"
    name = "异环"
    platform = "tajiduo"
    site = "https://www.tajiduo.com/bbs/index.html#/home?id=2"

    def validate(self, ctx: RunContext) -> RunResult:
        client = TajiduoClient(ctx)
        roles = client.roles()
        if not roles:
            return RunResult("error", "未找到异环角色，请先在塔吉多绑定", [])
        return RunResult("success", f"登录有效，找到 {len(roles)} 个异环角色", [x["name"] for x in roles])

    def run(self, ctx: RunContext) -> RunResult:
        client = TajiduoClient(ctx)
        roles = client.roles()
        if not roles:
            return RunResult("error", "未找到异环角色，请先在塔吉多绑定", [])
        outcomes, details = [], []
        for role in roles:
            try:
                try:
                    is_signed = client.confirms_role_today(client.state(), role, len(roles))
                except NeedLoginError:
                    raise
                except RuntimeError:
                    is_signed = False
                if is_signed:
                    status, message = "already_signed", "今日已签到"
                else:
                    try:
                        status, message = client.sign(role, len(roles))
                    except NeedLoginError:
                        raise
                    except RuntimeError:
                        try:
                            confirmed = client.confirms_role_today(client.state(), role, len(roles))
                        except NeedLoginError:
                            raise
                        except RuntimeError:
                            confirmed = False
                        status = "success" if confirmed else "error"
                        message = "已通过服务端状态确认成功" if confirmed else "签到结果未能确认，请稍后重试或在官方社区核对"
                outcomes.append(status)
                details.append(f"{role['name']}：{message}")
            except NeedLoginError:
                outcomes.append("needs_login")
                details.append(f"{role['name']}：需要重新登录或人工验证")
            except Exception:
                outcomes.append("error")
                details.append(f"{role['name']}：请求失败，请检查网络或更新适配器")
            ctx.log(details[-1])
        if "needs_login" in outcomes:
            return RunResult("needs_login", "部分异环角色需要重新登录或人工验证", details)
        if "error" in outcomes:
            return RunResult("error", "部分异环角色签到失败或结果未确认", details)
        status = "already_signed" if all(x == "already_signed" for x in outcomes) else "success"
        return RunResult(status, f"{len(roles)} 个角色均已完成今日签到", details)


MODULES = [TajiduoNTE()]
