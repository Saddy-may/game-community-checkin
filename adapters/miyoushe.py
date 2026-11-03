"""米游社国服星铁：只处理游戏签到，不执行社区积分任务。"""
from __future__ import annotations

import hashlib
import random
import string
import time
import uuid

from checkin_core import NeedLoginError, RunResult


class StarRailModule:
    id = "starrail"
    name = "崩坏：星穹铁道"
    platform = "miyoushe"
    site = "https://act.mihoyo.com/bbs/event/signin/hkrpg/index.html?act_id=e202304121516551"
    description = "米游社 · 国服游戏签到"
    ACT = "e202304121516551"
    BASE = "https://api-takumi.mihoyo.com"

    def _headers(self, ctx):
        cookies = ctx.credential.get("cookies", {})
        if not isinstance(cookies, dict) or not any(cookies.get(k) for k in ("cookie_token", "cookie_token_v2")):
            raise NeedLoginError("请登录米游社，取得可用于游戏签到的登录状态")
        stamp = str(int(time.time()))
        nonce = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
        digest = hashlib.md5(f"salt=4751cb5557bfad5e249e58462c39fb0a&t={stamp}&r={nonce}".encode()).hexdigest()
        device_id = ctx.credential.get("device_id") or str(uuid.uuid5(uuid.NAMESPACE_URL, str(cookies.get("ltuid_v2", cookies.get("ltuid", "community-checkin")))))
        return {
            "Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items()),
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/132.0.0.0 Safari/537.36",
            "Referer": self.site,
            "Origin": "https://act.mihoyo.com",
            "DS": f"{stamp},{nonce},{digest}",
            "x-rpc-app_version": "2.117.0",
            "x-rpc-client_type": "5",
            "x-rpc-device_id": device_id,
            "x-rpc-signgame": "hkrpg",
        }

    def _call(self, ctx, path, method="GET", **kwargs):
        response = ctx.session.request(method, self.BASE + path, headers=self._headers(ctx), timeout=20, allow_redirects=False, **kwargs)
        if response.status_code in (401, 403):
            raise NeedLoginError("米游社登录状态失效，请重新登录")
        response.raise_for_status()
        data = response.json()
        code = data.get("retcode")
        if code in (-100, 10001, -10001):
            raise NeedLoginError("米游社签到登录状态失效，请重新登录")
        if code not in (0, -5003):
            raise RuntimeError(f"米游社请求未完成（{code}）：{data.get('message', '接口响应异常')}")
        return data

    def _roles(self, ctx):
        data = self._call(ctx, "/binding/api/getUserGameRolesByCookie", params={"game_biz": "hkrpg_cn"})
        roles = data.get("data", {}).get("list", [])
        if not isinstance(roles, list) or not roles:
            raise RuntimeError("当前米游社账号未查询到国服星铁角色")
        return roles

    def _state(self, ctx, role):
        state = self._call(ctx, "/event/luna/info", params={"lang": "zh-cn", "act_id": self.ACT, "region": role["region"], "uid": role["game_uid"]}).get("data")
        if not isinstance(state, dict) or not isinstance(state.get("is_sign"), bool):
            raise RuntimeError("未取得有效的今日签到状态，请稍后重试")
        return state

    def validate(self, ctx):
        # 社区可查角色不等于签到会话有效，必须实际读取签到状态。
        try:
            roles = self._roles(ctx)
            for role in roles:
                self._state(ctx, role)
            return RunResult("success", f"登录有效，已找到 {len(roles)} 个星铁角色")
        except NeedLoginError:
            raise
        except Exception:
            return RunResult("error", "尚未确认星铁签到登录状态，请检查网络或重新登录")

    def run(self, ctx):
        roles = self._roles(ctx)
        details, errors, changed = [], [], False
        for role in roles:
            label = role.get("nickname") or "星铁角色"
            try:
                state = self._state(ctx, role)
                if state.get("is_sign"):
                    details.append(f"{label}：今天已签到")
                    continue
                if state.get("first_bind"):
                    raise NeedLoginError("首次绑定需要在官方签到页手动签到一次")
                try:
                    result = self._call(ctx, "/event/luna/sign", method="POST", json={"act_id": self.ACT, "region": role["region"], "uid": role["game_uid"]})
                except Exception:
                    # 提交超时可能已生效；先查询结果，避免盲目重发。
                    if self._state(ctx, role).get("is_sign"):
                        details.append(f"{label}：已核实签到完成")
                        changed = True
                        continue
                    raise
                body = result.get("data") or {}
                if body.get("success") == 1 or body.get("gt") or body.get("challenge"):
                    raise NeedLoginError("米游社要求人机验证，请打开官方签到页完成验证后重试")
                if not self._state(ctx, role).get("is_sign"):
                    raise RuntimeError("提交后尚未确认签到成功，请稍后重试")
                details.append(f"{label}：签到成功")
                changed = True
            except NeedLoginError:
                raise
            except Exception as exc:
                errors.append(f"{label}：{exc}")
        if errors:
            return RunResult("error", "部分角色未完成签到", details + errors)
        return RunResult("success" if changed else "already_signed", "星铁签到完成" if changed else "今天已签到", details)


MODULES = [StarRailModule()]
