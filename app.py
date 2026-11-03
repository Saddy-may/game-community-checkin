"""桌面入口与后台单次执行入口。"""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
# 源码版依赖仅安装在项目内，不修改用户全局Python。
if not getattr(sys, "frozen", False) and (ROOT / "vendor").is_dir():
    sys.path.insert(0, str(ROOT / "vendor"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argparse
import json
import os

from checkin_core import CheckinEngine, CredentialVault, Registry, RunContext, SettingsStore, AlreadyRunning, beijing_now, redact
from scheduler import should_run


def create_services(data_dir=None):
    directory = Path(data_dir) if data_dir else ROOT / "data"
    directory.mkdir(parents=True, exist_ok=True)
    registry = Registry().discover(ROOT / "adapters", ROOT / "plugins")
    settings = SettingsStore(directory)
    vault = CredentialVault(directory)
    engine = CheckinEngine(registry, settings, vault, directory)
    return directory, registry, settings, vault, engine


def main(argv=None):
    parser = argparse.ArgumentParser(description="游戏社区签到助手")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--scheduled", action="store_true")
    parser.add_argument("--module", action="append")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--check-login", metavar="MODULE")
    parser.add_argument("--import-gf2", metavar="CONFIG")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--data-dir", help=argparse.SUPPRESS)
    parser.add_argument("--self-check", metavar="REPORT", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    data, registry, settings, vault, engine = create_services(args.data_dir)
    if args.self_check:
        from checkin_core import _dpapi
        import customtkinter
        from playwright.sync_api import sync_playwright
        payload = b"community-checkin-packaged-selfcheck"
        encrypted = _dpapi(payload)
        report = {"ok": not registry.errors and len(registry.modules) >= 6 and _dpapi(encrypted, decrypt=True) == payload,
                  "module_count": len(registry.modules), "module_errors": registry.errors,
                  "encrypted_at_rest": payload not in encrypted, "ui_version": customtkinter.__version__,
                  "login_component": "available", "auto_enabled": settings.read()["auto_enabled"],
                  "background_enabled": settings.read()["background_enabled"]}
        Path(args.self_check).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0 if report["ok"] else 1
    if args.list:
        print(json.dumps({"games": [{"id": m.id, "name": m.name, "platform": m.platform} for m in registry.modules.values()], "load_errors": registry.errors}, ensure_ascii=False, indent=2))
        return 1 if registry.errors else 0
    if args.import_gf2:
        from auth import import_gf2_config
        credential, options = import_gf2_config(args.import_gf2)
        module = registry.modules["gf2"]
        context = RunContext(module.id, credential, {**getattr(module, "option_defaults", {}), **options})
        try:
            result = module.validate(context)
        finally:
            context.session.close()
        if not result.ok:
            raise RuntimeError(result.message)
        vault.set("gf2", credential)
        engine.invalidate_platform("gf2")
        settings.set_module("gf2", options={**settings.options_for("gf2"), **options})
        print("少前2已有社区登录已验证并加密导入")
        return 0
    if args.check_login:
        module = registry.modules[args.check_login]
        context = RunContext(module.id, vault.get(module.platform), settings.options_for(module.id), save_credential=lambda value: vault.set(module.platform, value))
        try:
            result = module.validate(context)
        finally:
            context.session.close()
        print(json.dumps({"status": result.status, "message": redact(result.message, context.credential)}, ensure_ascii=False))
        return 0 if result.ok else 1
    if args.headless:
        if args.scheduled:
            config = settings.read()
            if not config["background_enabled"] or not should_run(beijing_now()):
                return 0
        try:
            results = engine.run(args.module, force=args.force, source="background" if args.scheduled else "manual")
        except AlreadyRunning:
            return 0
        incomplete = [getattr(registry.modules.get(k), "name", k) for k, value in results.items() if value.status in ("error", "needs_login")]
        if incomplete:
            from notify import notify
            notify("签到助手需要处理", "、".join(incomplete) + "尚未完成，请打开助手查看或重新登录。")
        # 验证码/登录失效不触发系统反复重试；网络失败由Windows有限重试。
        return 1 if any(value.status == "error" for value in results.values()) else 0
    import customtkinter as ctk
    from gui import CheckinWindow
    ctk.set_appearance_mode("light")
    root = ctk.CTk()
    icon = ROOT / "tools" / "checkin.ico"
    if icon.exists():
        root.iconbitmap(str(icon))
    CheckinWindow(root, ROOT, data, registry, settings, vault, engine)
    root.mainloop()
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception as exc:
        # 避免无人值守进程的异常弹出控制台或输出原始登录信息。
        if "--headless" in sys.argv:
            code = 1
        elif getattr(sys, "frozen", False):
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, f"助手未能完成操作（{type(exc).__name__}）。请重试或查看本地设置。", "签到助手", 0x10)
            code = 1
        else:
            raise
    raise SystemExit(code)
