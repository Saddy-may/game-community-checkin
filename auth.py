"""官方网页登录。浏览器仅收集用户主动登录的本平台会话，不代填密码或验证码。"""
from __future__ import annotations

import json
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlparse

from checkin_core import RunContext, SUCCESS_STATUSES

LOGIN_SITES = {
    "skland": ("森空岛", "https://www.skland.com/"),
    "miyoushe": ("米游社", "https://www.miyoushe.com/sr/"),
    "kuro": ("库街区", "https://www.kurobbs.com/mc/home/9"),
    "gf2": ("少前2官方社区", "https://gf2-bbs.exiliumgf.com/"),
    "tajiduo": ("塔吉多", "https://www.tajiduo.com/bbs/index.html#/home?id=2"),
}
ALLOWED_DOMAINS = {
    "skland": ("skland.com", "hypergryph.com"),
    "miyoushe": ("miyoushe.com", "mihoyo.com"),
    "kuro": ("kurobbs.com",),
    "gf2": ("exiliumgf.com", "sunborngame.com"),
    "tajiduo": ("tajiduo.com", "laohu.com", "wanmei.com"),
}


def belongs(host, domains):
    host = (host or "").lstrip(".").lower()
    return any(host == d or host.endswith("." + d) for d in domains)


def token_values(value, depth=0):
    """只从官方会话对象中抽取已知字段，不把整个浏览器存储写入数据文件。"""
    if depth > 6:
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return {}
    found = {}
    if isinstance(value, dict):
        for key, item in value.items():
            normal = key.replace("_", "").lower()
            mapped = {"token": "token", "accesstoken": "accessToken", "refreshtoken": "refreshToken", "userid": "user_id", "uid": "uid", "deviceid": "deviceId", "devcode": "devcode", "distinctid": "distinct_id"}.get(normal)
            if mapped and isinstance(item, (str, int)) and item:
                found[mapped] = item
            elif isinstance(item, (dict, list)) or (isinstance(item, str) and item.startswith(("{", "["))):
                found.update(token_values(item, depth + 1))
    elif isinstance(value, list):
        for item in value[:30]:
            found.update(token_values(item, depth + 1))
    return found


def import_gf2_config(path: str | Path) -> tuple[dict, dict]:
    """只读取gf2gacha已保存的社区会话和兑换顺序，不读取游戏登录日志。"""
    path = Path(path)
    raw = path.read_text(encoding="utf-8-sig")
    try:
        import yaml
        data = yaml.safe_load(raw) or {}
        credentials = []
        for value in data.values():
            if isinstance(value, dict):
                token = value.get("webToken") or value.get("webtoken")
                if token:
                    credentials.append({"token": str(token)})
        options = {}
        priority = data.get("exchangeList") or data.get("exchangelist")
        if isinstance(priority, list) and priority:
            options["exchange_priority"] = [str(x) for x in priority] + ["*"]
    except ImportError:
        credentials = [{"token": x} for x in re.findall(r"^\s*webtoken\s*:\s*[\"']?([^\s\"']+)", raw, re.M | re.I)]
        options = {}
    if not credentials:
        raise ValueError("这个配置文件没有可用的社区登录信息，请改用官方网页登录")
    if len(credentials) > 1:
        raise ValueError("配置中有多个账号，请使用官方网页登录选择需要的账号")
    return credentials[0], options


class BrowserLogin:
    """在工作线程中使用独立临时浏览器；用户自行操作登录。"""
    def __init__(self, platform, module, options, on_message, on_success, on_finish):
        self.platform, self.module, self.options = platform, module, options
        self.on_message, self.on_success, self.on_finish = on_message, on_success, on_finish
        self.cancel = threading.Event()
        self.check = threading.Event()
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._run, name="official-login", daemon=True)
        self.thread.start()

    def _validate(self, credential):
        updated = dict(credential)
        def save(value):
            value = dict(value)
            updated.clear()
            updated.update(value)
        ctx = RunContext(self.module.id, updated, self.options, save_credential=save)
        fn = getattr(self.module, "validate", None)
        if fn is None:
            raise RuntimeError("该扩展尚未提供登录状态检查")
        try:
            result = fn(ctx)
        finally:
            ctx.session.close()
        if result.status not in SUCCESS_STATUSES:
            raise RuntimeError(result.message)
        return updated, result.message + (" · " + "；".join(result.details) if result.details else "")

    def _run(self):
        platform = self.platform
        captured = {}
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = None
                for channel in ("msedge", "chrome"):
                    try:
                        browser = p.chromium.launch(channel=channel, headless=False)
                        break
                    except Exception:
                        pass
                if browser is None:
                    raise RuntimeError("未找到可打开的 Edge 或 Chrome，请先安装其中一款浏览器")
                context = browser.new_context(viewport={"width": 1100, "height": 780}, locale="zh-CN")

                def on_request(request):
                    if not belongs(urlparse(request.url).hostname, ALLOWED_DOMAINS[platform]):
                        return
                    try:
                        headers = request.all_headers()
                        if platform == "skland" and headers.get("did"):
                            captured["dId"] = headers["did"]
                        elif platform == "gf2" and headers.get("authorization"):
                            captured["token"] = headers["authorization"]
                        elif platform == "kuro" and headers.get("token"):
                            captured["token"] = headers["token"]
                            for key in ("devcode", "distinct_id", "source", "version"):
                                if headers.get(key):
                                    captured[key] = headers[key]
                        elif platform == "tajiduo" and urlparse(request.url).hostname == "bbs-api.tajiduo.com":
                            if headers.get("uid"):
                                captured["uid"] = headers["uid"]
                            if headers.get("deviceid") or headers.get("device-id"):
                                captured["deviceId"] = headers.get("deviceid") or headers.get("device-id")
                            for key in ("accesstoken", "access-token", "token", "authorization"):
                                if headers.get(key):
                                    captured["accessToken"] = headers[key].removeprefix("Bearer ")
                    except Exception:
                        pass

                def on_response(response):
                    host = urlparse(response.url).hostname
                    if platform not in ("kuro", "tajiduo") or not belongs(host, ALLOWED_DOMAINS[platform]):
                        return
                    if not any(x in urlparse(response.url).path.lower() for x in ("login", "token", "account")):
                        return
                    try:
                        captured.update(token_values(response.json()))
                    except Exception:
                        pass

                context.on("request", on_request)
                context.on("response", on_response)
                page = context.new_page()
                page.goto(LOGIN_SITES[platform][1], wait_until="domcontentloaded", timeout=60000)
                self.on_message("请在新打开的官方页面登录，完成后回到助手点击“检查登录”")
                deadline = time.monotonic() + 900
                while time.monotonic() < deadline and not self.cancel.is_set():
                    if not context.pages:
                        break
                    # Playwright事件泵只在此工作线程内运行。
                    try:
                        context.pages[0].wait_for_timeout(250)
                    except Exception:
                        break
                    if not self.check.is_set():
                        continue
                    self.check.clear()
                    self.on_message("正在检查官方登录状态…")
                    try:
                        candidate = dict(captured)
                        pages = [pg for pg in context.pages if belongs(urlparse(pg.url).hostname, ALLOWED_DOMAINS[platform])]
                        if platform == "miyoushe":
                            cookies = {c["name"]: c["value"] for c in context.cookies() if belongs(c.get("domain"), ALLOWED_DOMAINS[platform])}
                            candidate = {"cookies": cookies}
                        elif platform == "skland":
                            response = context.request.get("https://web-api.skland.com/account/info/hg", timeout=20000)
                            data = response.json()
                            content = data.get("content") or (data.get("data") or {}).get("content")
                            if isinstance(content, str) and content:
                                candidate = {**candidate, "token": content}
                        else:
                            for pg in pages:
                                store = pg.evaluate("() => ({...localStorage,...sessionStorage})")
                                if platform == "gf2" and store.get("key"):
                                    candidate["token"] = store["key"]
                                elif platform == "kuro":
                                    info = token_values(store.get("auth", {}))
                                    candidate = {**info, **candidate}
                                    if store.get("dc"):
                                        candidate.setdefault("devcode", store["dc"])
                                    if store.get("distinct_id") or store.get("dc"):
                                        candidate.setdefault("distinct_id", store.get("distinct_id") or store.get("dc"))
                                    candidate.setdefault("source", "h5")
                                    candidate.setdefault("version", "3.3.2")
                                    web_token = store.get("auth_token")
                                    if web_token and isinstance(web_token, str):
                                        try:
                                            web_token = json.loads(web_token)
                                        except ValueError:
                                            pass
                                        if isinstance(web_token, str):
                                            candidate["token"] = web_token
                                            if info.get("user_id"):
                                                candidate["user_id"] = info["user_id"]
                                            if info.get("refreshToken"):
                                                candidate["refreshToken"] = info["refreshToken"]
                                elif platform == "tajiduo":
                                    # 官方签到H5通过App bridge使用此键；普通PC社区
                                    # 的OAuth Cookie登录不等于游戏签到授权。
                                    web_token = store.get("HT_USER_ACCESS_TOKEN")
                                    if isinstance(web_token, str) and web_token:
                                        candidate["accessToken"] = web_token
                                    candidate = {**token_values(store), **candidate}
                                else:
                                    from_store = token_values(store)
                                    candidate = {**from_store, **candidate}
                        if not candidate:
                            raise ValueError("还没有取得登录状态，请先在官方页面完成登录")
                        if platform == "tajiduo" and not (candidate.get("accessToken") or candidate.get("refreshToken")):
                            raise ValueError("当前是塔吉多网页社区登录，请返回助手使用短信登录，取得异环签到授权")
                        candidate, message = self._validate(candidate)
                        if self.cancel.is_set():
                            break
                        self.on_success(candidate, message)
                        break
                    except Exception as exc:
                        # 不把远端返回体、Cookie、会话参数等输出到界面。
                        text = str(exc)
                        if any(word in text.lower() for word in ("token=", "authorization", "cookie=", "eyj")):
                            text = "登录状态尚未通过检查，请完成登录后再试"
                        self.on_message(text[:180])
                browser.close()
        except ImportError:
            self.on_message("网页登录组件尚未就绪，请运行“安装依赖”或使用完整桌面版")
        except Exception as exc:
            self.on_message(f"网页登录未完成（{type(exc).__name__}），可重试或使用本地导入")
        finally:
            self.on_finish()
