"""少女前线2官方社区：独立社区会话、每日任务及积分兑换。

Protocol references: official gf2-bbs.exiliumgf.com frontend;
Tsuk1ko/gf2-bbs-sign-in (AGPL-3.0); gf2gacha configuration interoperability.
See THIRD_PARTY_NOTICES.md for provenance and modification details.
Only community points are spent. No game login, packet capture or paid purchase.
"""
from __future__ import annotations

import time
from typing import Any

import requests

from checkin_core import NeedLoginError, RunContext, RunResult


class CommunityError(RuntimeError):
    pass


class _Client:
    BASE = "https://gf2-bbs-api.exiliumgf.com"

    def __init__(self, ctx: RunContext):
        self.ctx = ctx
        self.token = str(ctx.credential.get("token") or "").strip()
        if not self.token:
            raise NeedLoginError("请先登录少女前线2官方社区")
        self.timeout = max(5, min(float(ctx.options.get("timeout", 20)), 60))

    def call(self, method: str, path: str, payload: dict | None = None) -> dict:
        kwargs = {"params": payload} if method == "GET" else {"json": payload or {}}
        response = self.ctx.session.request(
            method, self.BASE + path, timeout=(8, self.timeout), allow_redirects=False,
            headers={"Authorization": self.token, "Accept": "application/json",
                     "Content-Type": "application/json", "Origin": "https://gf2-bbs.exiliumgf.com",
                     "Referer": "https://gf2-bbs.exiliumgf.com/"}, **kwargs)
        if response.status_code in (401, 403):
            raise NeedLoginError("少女前线2社区登录已失效，请重新登录社区")
        response.raise_for_status()
        if not 200 <= response.status_code < 300:
            raise CommunityError("社区接口发生跳转，未继续发送登录凭据")
        try:
            body = response.json()
        except (ValueError, TypeError) as exc:
            raise CommunityError("少女前线2社区返回了无法识别的内容") from exc
        if not isinstance(body, dict) or "Code" not in body:
            raise CommunityError("少女前线2社区响应缺少结果代码")
        code = str(body["Code"])
        message = str(body.get("Message") or "")
        if code in {"-1", "10004", "30003", "401", "403"}:
            raise NeedLoginError("少女前线2社区登录已失效，请重新登录社区")
        if any(word in message.lower() for word in ("验证码", "人机", "captcha", "geetest")):
            raise NeedLoginError("少女前线2社区需要你完成登录验证")
        if code != "0":
            if code == "30005":
                raise CommunityError("此社区账号未查询到少女前线2游戏角色")
            raise CommunityError(f"少女前线2社区操作未成功（代码 {code}）")
        data = body.get("data")
        if data is None and ("/community/topic/like/" in path or "/community/topic/share/" in path):
            return {}
        if not isinstance(data, dict):
            raise CommunityError("少女前线2社区响应内容不完整")
        return data

    def user(self) -> dict:
        user = self.call("POST", "/community/member/info").get("user")
        if not isinstance(user, dict) or not user.get("game_uid"):
            raise CommunityError("当前社区账号没有可确认的少女前线2游戏角色")
        expected = str(self.ctx.credential.get("game_uid") or self.ctx.options.get("game_uid") or "")
        if expected and str(user["game_uid"]) != expected:
            raise CommunityError("社区登录关联的游戏角色与已保存角色不一致，请核对账号")
        return user

    def tasks(self) -> list[dict]:
        items = self.call("GET", "/community/task/get_current_task_list").get("daily_task")
        if not isinstance(items, list) or any(not isinstance(x, dict) for x in items):
            raise CommunityError("未取得完整的每日社区任务列表")
        return items

    def exchange_items(self) -> list[dict]:
        items = self.call("GET", "/community/item/exchange_list").get("list")
        if not isinstance(items, list) or any(not isinstance(x, dict) for x in items):
            raise CommunityError("未取得完整的积分兑换列表")
        return items


class GF2Adapter:
    id = "gf2"
    name = "少女前线2：追放"
    platform = "gf2"
    site = "https://gf2-bbs.exiliumgf.com/"
    description = "官方社区签到、每日任务及积分兑换；奖励到游戏邮件领取"
    option_defaults = {"daily_tasks": True, "exchange": True, "exchange_max_per_run": 20,
                       "exchange_priority": ["基原信息核", "情报拼图", "萨狄斯金", "战场报告", "解析图纸", "*"],
                       "timeout": 20, "action_delay": 0.8}

    @staticmethod
    def _role_text(user: dict) -> str:
        return f"游戏角色 {user.get('game_nick_name') or user.get('nick_name') or ''}（UID {user['game_uid']}）"

    def validate(self, ctx: RunContext) -> RunResult:
        try:
            user = _Client(ctx).user()
            # Pin the verified game role in the candidate credentials. The caller
            # decides whether to persist it; validation makes no account changes.
            ctx.credential.setdefault("game_uid", user["game_uid"])
            return RunResult("success", "社区登录有效", [self._role_text(user)])
        except NeedLoginError:
            raise
        except (CommunityError, requests.RequestException, ValueError) as exc:
            return RunResult("error", self._error_message(exc))

    @staticmethod
    def _error_message(exc: Exception) -> str:
        if isinstance(exc, requests.RequestException):
            return "连接少女前线2社区失败，未确认完成，请检查网络后重试"
        return str(exc)

    @staticmethod
    def _count(item: dict) -> tuple[int, int]:
        try:
            count, maximum = int(item["complete_count"]), int(item["max_complete_count"])
            if count < 0 or maximum < 0:
                raise ValueError()
            return count, maximum
        except (KeyError, TypeError, ValueError) as exc:
            raise CommunityError("社区任务进度数据不完整") from exc

    @staticmethod
    def _pause(ctx: RunContext):
        time.sleep(max(0, min(float(ctx.options.get("action_delay", 0.8)), 5)))

    def _sign(self, client: _Client, details: list[str]) -> bool:
        path = "/community/task/get_current_sign_in_status"
        state = client.call("GET", path)
        if not isinstance(state.get("has_sign_in"), bool):
            raise CommunityError("未取得今日签到状态")
        if state["has_sign_in"]:
            details.append("今日社区已签到")
            return False
        # An uncertain submission is checked by a read, never blindly replayed.
        try:
            client.call("POST", "/community/task/sign_in")
        except requests.RequestException:
            if client.call("GET", path).get("has_sign_in") is not True:
                raise CommunityError("签到提交后连接中断，未确认成功；本轮不重复提交")
        except CommunityError:
            if client.call("GET", path).get("has_sign_in") is not True:
                raise
        if client.call("GET", path).get("has_sign_in") is not True:
            raise CommunityError("签到请求已返回，但尚未确认今日签到完成")
        details.append("社区签到已完成，游戏奖励请到邮件领取")
        return True

    def _daily_tasks(self, client: _Client, details: list[str]) -> tuple[bool, bool]:
        initial = client.tasks()
        incomplete = [x for x in initial if self._count(x)[0] < self._count(x)[1]]
        if not incomplete:
            details.append("每日社区任务均已完成")
            return False, True
        listing = client.call("GET", "/community/topic/list", {
            "sort_type": 1, "category_id": 1, "query_type": 1, "last_tid": 0,
            "pub_time": 0, "reply_time": 0, "hot_value": 0, "update_time": 0, "is_new_mark": 0})
        posts = listing.get("list")
        if not isinstance(posts, list):
            raise CommunityError("没有取得用于每日任务的帖子列表")
        posts = [x for x in posts if isinstance(x, dict) and str(x.get("topic_id", "")).isdigit()
                 and str(x.get("status", 0)) == "0"][:30]
        changed = False
        known = {"浏览帖子", "点赞帖子", "分享帖子"}
        for task in incomplete:
            name = str(task.get("task_name") or "")
            if name not in known:
                details.append(f"遇到尚未接入的每日任务：{name or '未命名任务'}")
                continue
            for post in posts:
                current = next((x for x in client.tasks() if x.get("task_name") == name), None)
                if current is None:
                    raise CommunityError("社区每日任务列表在执行中发生变化")
                before, maximum = self._count(current)
                if before >= maximum:
                    break
                tid = str(post["topic_id"])
                try:
                    if name == "浏览帖子":
                        client.call("GET", f"/community/topic/{tid}", {"id": tid})
                    elif name == "点赞帖子":
                        post_info = client.call("GET", f"/community/topic/{tid}", {"id": tid})
                        post_info = post_info.get("topic", post_info)
                        if not isinstance(post_info, dict) or "is_like" not in post_info:
                            continue
                        if post_info["is_like"]:
                            continue  # Never undo an existing like.
                        client.call("GET", f"/community/topic/like/{tid}", {"id": tid})
                    else:
                        # Official community task counter; no external message is sent.
                        client.call("GET", f"/community/topic/share/{tid}", {"id": tid})
                    self._pause(client.ctx)
                    after_task = next((x for x in client.tasks() if x.get("task_name") == name), None)
                    if after_task is not None and self._count(after_task)[0] > before:
                        changed = True
                except NeedLoginError:
                    raise
                except (CommunityError, requests.RequestException):
                    client.ctx.log(f"{name}的一条操作未确认成功，继续核对其它帖子")
        final = client.tasks()
        remaining = []
        for item in final:
            count, maximum = self._count(item)
            details.append(f"{item.get('task_name', '每日任务')}：{count}/{maximum}")
            if count < maximum:
                remaining.append(item)
        return changed, not remaining

    def _exchange(self, client: _Client, details: list[str]) -> tuple[bool, bool]:
        priorities = client.ctx.options.get("exchange_priority", self.option_defaults["exchange_priority"])
        if not isinstance(priorities, list):
            raise CommunityError("兑换优先顺序应为列表")
        priorities = [str(x) for x in priorities]
        limit = max(0, min(int(client.ctx.options.get("exchange_max_per_run", 20)), 100))
        per_item_limits = client.ctx.options.get("exchange_item_daily_limits", {})
        if not isinstance(per_item_limits, dict):
            raise CommunityError("每项每日兑换限额格式不正确")
        changed, total = False, 0
        items = client.exchange_items()

        def rank(item: dict) -> int:
            return next((i for i, rule in enumerate(priorities)
                         if rule == "*" or rule == str(item.get("exchange_id"))
                         or rule in str(item.get("item_name", ""))), len(priorities))

        selected = [x for x in items if rank(x) < len(priorities)]
        for item in sorted(selected, key=rank):
            item_id = item.get("exchange_id")
            if not str(item_id).isdigit():
                raise CommunityError("积分兑换物品缺少有效编号")
            name = str(item.get("item_name") or f"物品 {item_id}")
            while total < limit:
                fresh = next((x for x in client.exchange_items()
                              if str(x.get("exchange_id")) == str(item_id)), None)
                if fresh is None:
                    break
                try:
                    count, maximum, cost = (int(fresh[k]) for k in
                                            ("exchange_count", "max_exchange_count", "use_score"))
                    score = int(client.user()["score"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise CommunityError("积分或兑换次数数据不完整，已停止兑换") from exc
                if count < 0 or maximum < 0 or cost <= 0:
                    raise CommunityError("兑换价格或限额异常，已停止兑换")
                daily_cap = per_item_limits.get(str(item_id), per_item_limits.get(name))
                if daily_cap is not None and str(fresh.get("cycle")) == "day":
                    maximum = min(maximum, max(0, int(daily_cap)))
                if count >= maximum:
                    break
                if score < cost:
                    details.append(f"{name}：当前积分不足，暂未兑换")
                    break
                uncertain = False
                try:
                    client.call("POST", "/community/item/exchange", {"exchange_id": int(item_id)})
                except requests.RequestException:
                    uncertain = True
                after = next((x for x in client.exchange_items()
                              if str(x.get("exchange_id")) == str(item_id)), None)
                client.user()  # Re-read both authoritative inventory and points after submission.
                try:
                    new_count = int(after["exchange_count"]) if after else count
                except (KeyError, TypeError, ValueError) as exc:
                    raise CommunityError("兑换后无法核实次数，本轮不重复提交") from exc
                if new_count <= count:
                    suffix = "连接中断" if uncertain else "结果未确认"
                    raise CommunityError(f"{name}兑换{suffix}，本轮停止兑换，避免重复消耗积分")
                details.append(f"已确认兑换：{name}")
                changed, total = True, total + 1
                self._pause(client.ctx)
        if total >= limit and limit > 0:
            details.append(f"已达到本轮兑换上限 {limit} 次")
        elif not changed:
            details.append("本轮没有需要或能够兑换的物品")
        return changed, True

    def run(self, ctx: RunContext) -> RunResult:
        details: list[str] = []
        changed, complete = False, True
        try:
            client = _Client(ctx)
            details.append(self._role_text(client.user()))
            changed = self._sign(client, details)
            if ctx.options.get("daily_tasks", True):
                task_changed, tasks_complete = self._daily_tasks(client, details)
                changed, complete = changed or task_changed, complete and tasks_complete
            if ctx.options.get("exchange", True):
                exchange_changed, exchange_complete = self._exchange(client, details)
                changed, complete = changed or exchange_changed, complete and exchange_complete
            if not complete:
                return RunResult("error", "签到已核对，仍有每日社区任务未完成", details)
            status = "success" if changed else "already_signed"
            return RunResult(status, "少女前线2社区任务已完成" if changed else "今日社区任务已处理", details)
        except NeedLoginError:
            raise
        except (CommunityError, requests.RequestException, ValueError) as exc:
            return RunResult("error", self._error_message(exc), details)


MODULES = [GF2Adapter()]
