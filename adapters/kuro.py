"""国服鸣潮游戏签到。只处理 gameId=3，分别记录每个绑定角色。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import requests

from checkin_core import NeedLoginError, RunContext, RunResult


class KuroError(RuntimeError):
    pass


class _Client:
    BASE = "https://api.kurobbs.com"

    def __init__(self, ctx: RunContext):
        self.ctx = ctx
        self.token = str(ctx.credential.get("token") or "").strip()
        if not self.token:
            raise NeedLoginError("请先登录库街区，以获取鸣潮签到授权")

    def post(self, path: str, data: dict, *, allow_already: bool = False) -> dict:
        source = str(self.ctx.credential.get("source") or "h5")
        version = str(self.ctx.credential.get("api_version") or self.ctx.credential.get("version")
                      or ("3.3.2" if source == "h5" else "2.2.0"))
        headers = {
            "token": self.token, "source": source, "lang": "zh-Hans",
            "version": version,
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
            "Accept": "application/json",
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "Chrome/132.0.0.0 Safari/537.36") if source == "h5" else "okhttp/3.10.0",
            "Origin": "https://www.kurobbs.com", "Referer": "https://www.kurobbs.com/mc/home/9",
            "devcode": str(self.ctx.credential.get("devcode") or ""),
            "distinct_id": str(self.ctx.credential.get("distinct_id") or ""),
        }
        timeout = max(5, min(float(self.ctx.options.get("timeout", 20)), 60))
        response = self.ctx.session.request("POST", self.BASE + path, headers=headers,
                                            data=data, timeout=(8, timeout), allow_redirects=False)
        if response.status_code in (401, 403):
            raise NeedLoginError("库街区登录已失效，请重新登录")
        response.raise_for_status()
        if not 200 <= response.status_code < 300:
            raise KuroError("库街区接口发生跳转，未继续发送登录凭据")
        try:
            body = response.json()
        except (ValueError, TypeError) as exc:
            raise KuroError("库街区返回了无法识别的内容") from exc
        if not isinstance(body, dict) or "code" not in body:
            raise KuroError("库街区响应缺少结果代码")
        code = str(body["code"])
        message = str(body.get("msg") or "").lower()
        if code in {"220", "221", "222", "230", "401", "403", "10002"} or any(
                x in message for x in ("登录已过期", "登录失效", "请先登录", "token失效", "token expired")):
            raise NeedLoginError("库街区登录已失效，请重新登录")
        if any(x in message for x in ("验证码", "人机", "captcha", "geetest")):
            raise NeedLoginError("库街区需要你完成验证后再签到")
        if code == "1511" and allow_already:
            return body
        if code != "200" or body.get("success") is False:
            raise KuroError(f"库街区操作未成功（代码 {code}）")
        return body

    def identity_and_roles(self) -> tuple[str, list[dict]]:
        expected = str(self.ctx.credential.get("user_id") or "")
        # The current official web client uses viewUserId, not the old app's type=1.
        params = {"viewUserId": expected} if expected else {"type": 1}
        data = self.post("/user/mineV2", params).get("data")
        mine = data.get("mine") if isinstance(data, dict) else None
        if not isinstance(mine, dict) or not mine.get("userId"):
            raise KuroError("未取得有效的库街区账号信息")
        user_id = str(mine["userId"])
        if expected and expected != user_id:
            raise KuroError("库街区账号与已保存账号不一致，请核对登录")
        raw = self.post("/user/role/findRoleList", {"gameId": "3"}).get("data")
        if isinstance(raw, dict):
            raw = raw.get("roleList")
        if not isinstance(raw, list):
            raise KuroError("未取得完整的鸣潮绑定角色列表")
        selected = self.ctx.options.get("role_ids") or []
        if not isinstance(selected, list):
            raise KuroError("鸣潮角色筛选应为角色编号列表")
        selected = {str(x) for x in selected}
        roles, seen = [], set()
        for role in raw:
            if not isinstance(role, dict) or str(role.get("gameId", "3")) != "3":
                continue
            role_id = str(role.get("roleId") or "")
            if not role_id or (selected and role_id not in selected):
                continue
            server_id = str(role.get("serverId") or "76402e5b20be2c39f095a152090afddc")
            key = (server_id, role_id)
            if key not in seen:
                seen.add(key)
                roles.append({**role, "gameId": "3", "roleId": role_id, "serverId": server_id})
        if selected - {str(x["roleId"]) for x in roles}:
            raise KuroError("部分指定鸣潮角色未在当前账号绑定，请核对角色选择")
        if not roles:
            raise KuroError("库街区账号尚未找到可签到的鸣潮角色")
        return user_id, roles


class KuroAdapter:
    id = "wuwa"
    name = "鸣潮"
    platform = "kuro"
    site = "https://www.kurobbs.com/mc/home/9"
    description = "库街区国服鸣潮游戏签到，逐个核对绑定角色"
    option_defaults = {"role_ids": [], "timeout": 20}

    @staticmethod
    def _label(role: dict) -> str:
        return f"{role.get('roleName') or role.get('roleNickName') or '鸣潮角色'}（{role['roleId']}）"

    @staticmethod
    def _error_message(exc: Exception) -> str:
        if isinstance(exc, requests.RequestException):
            return "连接库街区失败，未确认签到结果，请检查网络后重试"
        return str(exc)

    def validate(self, ctx: RunContext) -> RunResult:
        try:
            _, roles = _Client(ctx).identity_and_roles()
            return RunResult("success", f"库街区登录有效，找到 {len(roles)} 个鸣潮角色",
                             [self._label(role) for role in roles])
        except NeedLoginError:
            raise
        except (KuroError, requests.RequestException, ValueError) as exc:
            return RunResult("error", self._error_message(exc))

    def run(self, ctx: RunContext) -> RunResult:
        details, errors, changed = [], 0, 0
        try:
            client = _Client(ctx)
            user_id, roles = client.identity_and_roles()
            month = datetime.now(timezone(timedelta(hours=8))).strftime("%m")
            for role in roles:
                label = self._label(role)
                try:
                    body = client.post("/encourage/signIn/v2", {
                        "gameId": "3", "serverId": role["serverId"], "roleId": role["roleId"],
                        "userId": str(role.get("userId") or user_id), "reqMonth": month}, allow_already=True)
                    if str(body["code"]) == "1511":
                        details.append(f"{label}：今日已签到")
                    else:
                        changed += 1
                        details.append(f"{label}：游戏签到成功")
                except NeedLoginError:
                    raise
                except (KuroError, requests.RequestException) as exc:
                    errors += 1
                    details.append(f"{label}：{self._error_message(exc)}")
            if errors:
                return RunResult("error", f"鸣潮有 {errors}/{len(roles)} 个角色未确认签到完成", details)
            return RunResult("success" if changed else "already_signed",
                             f"鸣潮 {len(roles)} 个角色签到已核对", details)
        except NeedLoginError:
            raise
        except (KuroError, requests.RequestException, ValueError) as exc:
            return RunResult("error", self._error_message(exc), details)


MODULES = [KuroAdapter()]
