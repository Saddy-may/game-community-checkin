from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import queue
import shutil
import threading
import time

import customtkinter as ctk
from PIL import Image, ImageDraw
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import webbrowser

from auth import BrowserLogin, LOGIN_SITES, import_gf2_config
from checkin_core import AlreadyRunning, Registry, RunContext, SUCCESS_STATUSES, beijing_now
from scheduler import DailyScheduler, next_run, register_background_task, remove_background_task, background_task_exists

BG = "#f2f5fa"
INK = "#18243c"
MUTED = "#64748b"
BLUE = "#3568e8"
FONT = "Microsoft YaHei UI"
BORDER = "#e4eaf3"
STATUS_NAMES = {"success": "已完成", "already_signed": "已完成", "needs_login": "需要登录", "error": "需要处理", "running": "进行中", "skipped": "已停用"}


class CheckinWindow:
    def __init__(self, root, project_dir, data_dir, registry, settings, vault, engine):
        self.root, self.project_dir, self.data_dir = root, Path(project_dir), Path(data_dir)
        self.registry, self.settings, self.vault, self.engine = registry, settings, vault, engine
        self.queue = queue.Queue()
        self.busy = False
        self.pending_scheduled = False
        self.login_job = None
        self.cards, self.images, self.last_platforms = {}, {}, set()
        self._closing, self.background_busy = False, False
        self._background_generation = 0
        self._poll_after, self._state_stamp, self._last_idle_check = None, None, 0
        self.engine.on_event = lambda value: self.queue.put(("event", value))
        ctk.set_appearance_mode("light")
        root.title("每日签到 · 游戏社区助手")
        root.geometry("1160x900")
        root.minsize(1000, 740)
        root.configure(fg_color=BG)
        root.option_add("*Font", (FONT, 12))
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=INK, font=(FONT, 12))
        style.configure("TCheckbutton", background=BG, foreground=INK, font=(FONT, 12))
        style.configure("TButton", font=(FONT, 12), padding=(12, 8))
        style.configure("Accent.TButton", background=BLUE, foreground="white", borderwidth=0)
        style.map("Accent.TButton", background=[("active", "#2858ce"), ("disabled", "#9bb3ef")])
        root.grid_columnconfigure(0, weight=1)
        root.grid_rowconfigure(2, weight=1)
        top = ctk.CTkFrame(root, fg_color="#14233d", corner_radius=0, height=110)
        top.grid(row=0, column=0, sticky="ew")
        top.grid_propagate(False)
        top.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(top, text="每日签到", text_color="white", font=(FONT, 29, "bold")).grid(row=0, column=0, sticky="w", padx=30, pady=(19, 0))
        ctk.CTkLabel(top, text="游戏社区助手  ·  每天的奖励，一处领取", text_color="#bdcbe1", font=(FONT, 12)).grid(row=1, column=0, sticky="w", padx=31, pady=(1, 19))
        ctk.CTkLabel(top, text=beijing_now().strftime("%Y / %m / %d"), text_color="#d4deee", font=(FONT, 13)).grid(row=0, column=1, rowspan=2, padx=32, sticky="e")
        bar = ctk.CTkFrame(root, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", padx=29, pady=(18, 8))
        self.summary = tk.StringVar(value="正在读取本地状态…")
        ctk.CTkLabel(bar, textvariable=self.summary, font=(FONT, 17, "bold"), text_color=INK).pack(side="left")
        self.run_button = self._button(bar, "一键签到", self.run_all, True, 124)
        self.run_button.pack(side="right")
        self._button(bar, "管理游戏", self.manage_games, width=100).pack(side="right", padx=(0, 10))
        self.tabs = ctk.CTkTabview(root, fg_color="transparent", corner_radius=14, text_color=INK,
            segmented_button_fg_color="#e6edf7", segmented_button_selected_color="white",
            segmented_button_selected_hover_color="white", segmented_button_unselected_color="#e6edf7",
            segmented_button_unselected_hover_color="#dce5f4")
        self.tabs.grid(row=2, column=0, sticky="nsew", padx=23, pady=(0, 8))
        self.tabs._segmented_button.configure(font=(FONT, 12))
        game_tab = self.tabs.add("我的游戏")
        history_tab = self.tabs.add("运行记录")
        settings_tab = self.tabs.add("自动签到与设置")
        game_tab.grid_columnconfigure(0, weight=1)
        game_tab.grid_rowconfigure(0, weight=1)
        self.card_area = ctk.CTkScrollableFrame(game_tab, fg_color="transparent", corner_radius=0,
            scrollbar_button_color="#ccd6e6", scrollbar_button_hover_color="#b1bfd4")
        self.card_area.grid(row=0, column=0, sticky="nsew")
        self.card_area.grid_columnconfigure((0, 1), weight=1, uniform="game")
        self._build_cards()
        history_tab.grid_columnconfigure(0, weight=1)
        history_tab.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(history_tab, text="每次执行的结果都会保存在这里。", text_color=MUTED, font=(FONT, 12)).grid(row=0, column=0, sticky="w", padx=10, pady=(15, 10))
        self.history = ctk.CTkTextbox(history_tab, fg_color="white", text_color=INK, corner_radius=16,
            border_width=1, border_color=BORDER, wrap="word", font=(FONT, 12))
        self.history.grid(row=1, column=0, sticky="nsew", padx=5, pady=(0, 6))
        self.history.configure(state="disabled")
        saved = settings.read()
        self.auto = tk.BooleanVar(value=saved.get("auto_enabled", False))
        self.background = tk.BooleanVar(value=saved.get("background_enabled", False))
        self.catch_up = tk.BooleanVar(value=saved.get("catch_up_on_start", True))
        self.background_hint = tk.StringVar(value="正在检查 Windows 后台任务状态…")
        setting_area = ctk.CTkScrollableFrame(settings_tab, fg_color="transparent", corner_radius=0)
        setting_area.pack(fill="both", expand=True, pady=(7, 0))
        schedule = ctk.CTkFrame(setting_area, fg_color="white", corner_radius=18, border_width=1, border_color=BORDER)
        schedule.pack(fill="x", padx=4, pady=(6, 16))
        ctk.CTkLabel(schedule, text="每天 00:00:10", text_color=INK, font=(FONT, 24, "bold")).pack(anchor="w", padx=24, pady=(20, 0))
        ctk.CTkLabel(schedule, text="北京时间 · 自动签到可随时开启或关闭", text_color=MUTED, font=(FONT, 12)).pack(anchor="w", padx=25, pady=(0, 18))
        self.auto_switch = self._setting_switch(schedule, "程序运行时自动签到", self.auto, self.toggle_auto,
            "保持助手运行，到时自动处理已启用的游戏。")
        self.background_switch = self._setting_switch(schedule, "关闭窗口后仍自动签到", self.background, self.toggle_background, self.background_hint)
        self.catch_up_switch = self._setting_switch(schedule, "错过时间后补跑当天任务", self.catch_up, self.toggle_catch_up,
            "开机登录或打开助手后补跑；关机期间无法执行，不能保证补回过去日期。")
        ctk.CTkLabel(schedule, text="后台执行时需保持当前 Windows 用户登录，锁屏不影响运行。", text_color=MUTED,
            font=(FONT, 12), anchor="w", wraplength=850).pack(anchor="w", padx=25, pady=(0, 21))
        local = ctk.CTkFrame(setting_area, fg_color="white", corner_radius=18, border_width=1, border_color=BORDER)
        local.pack(fill="x", padx=4, pady=(0, 14))
        ctk.CTkLabel(local, text="账号与本地数据", text_color=INK, font=(FONT, 17, "bold")).pack(anchor="w", padx=24, pady=(19, 10))
        actions = ctk.CTkFrame(local, fg_color="transparent")
        actions.pack(fill="x", padx=24, pady=(0, 12))
        self._button(actions, "导入少前2已有登录", self.import_gf2, width=168).pack(side="left")
        self._button(actions, "打开数据文件夹", lambda: os.startfile(self.data_dir), width=146).pack(side="left", padx=10)
        ctk.CTkLabel(local, text="登录信息由当前 Windows 用户加密保存。每款游戏可单独停用或隐藏。", text_color=MUTED,
            font=(FONT, 12), anchor="w", wraplength=850).pack(anchor="w", padx=25, pady=(0, 21))
        footer_frame = ctk.CTkFrame(root, height=49, corner_radius=0, fg_color="#eaf0f8")
        footer_frame.grid(row=3, column=0, sticky="ew")
        footer_frame.grid_columnconfigure(0, weight=1)
        self.footer = tk.StringVar(value="准备就绪")
        ctk.CTkLabel(footer_frame, textvariable=self.footer, text_color="#586b86", font=(FONT, 12), anchor="w",
            wraplength=1050, justify="left").grid(row=0, column=0, sticky="ew", padx=29, pady=12)
        self.timer = DailyScheduler(lambda: self.queue.put(("scheduled", None)), lambda: self.settings.read()["auto_enabled"],
            on_error=lambda text: self.queue.put(("notice", text)), catch_up=lambda: self.settings.read().get("catch_up_on_start", True))
        self.timer.start()
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.refresh()
        self._poll_after = root.after(150, self.poll)
        self._check_background_state()

    @staticmethod
    def _button(parent, text, command, primary=False, width=98):
        return ctk.CTkButton(parent, text=text, command=command, width=width, height=36, corner_radius=10,
            font=(FONT, 12, "bold" if primary else "normal"), border_width=0 if primary else 1, border_color=BORDER,
            fg_color=BLUE if primary else "white", hover_color="#2859ce" if primary else "#eff3fb", text_color="white" if primary else INK)

    def _setting_switch(self, parent, title, variable, command, description):
        line = ctk.CTkFrame(parent, fg_color="transparent")
        line.pack(fill="x", padx=25, pady=(0, 17))
        switch = ctk.CTkSwitch(line, text=title, variable=variable, command=command, font=(FONT, 14, "bold"),
            text_color=INK, progress_color=BLUE, button_color="white", button_hover_color="#edf2fb", fg_color="#ccd6e5",
            switch_width=40, switch_height=22)
        switch.pack(anchor="w")
        kwargs = {"textvariable": description} if isinstance(description, tk.Variable) else {"text": description}
        ctk.CTkLabel(line, **kwargs, text_color=MUTED, font=(FONT, 12), wraplength=820, justify="left", anchor="w").pack(anchor="w", padx=(52, 0), pady=(4, 0))
        return switch

    def _game_image(self, module_id):
        if module_id not in self.images:
            path = self.project_dir / "assets" / "icons" / f"{module_id}.png"
            try:
                with Image.open(path) as source:
                    picture = source.convert("RGBA").resize((144, 144), Image.Resampling.LANCZOS)
                mask = Image.new("L", picture.size)
                ImageDraw.Draw(mask).rounded_rectangle((0, 0, 143, 143), radius=31, fill=255)
                picture.putalpha(mask)
                self.images[module_id] = ctk.CTkImage(light_image=picture, dark_image=picture, size=(58, 58))
            except (OSError, ValueError):
                self.images[module_id] = None
        return self.images[module_id]

    def _build_cards(self):
        for widget in self.card_area.winfo_children():
            widget.destroy()
        self.cards = {}
        config = self.settings.read().get("modules", {})
        visible = [m for m in self.registry.modules.values() if not config.get(m.id, {}).get("hidden", False)]
        for i, module in enumerate(visible):
            frame = ctk.CTkFrame(self.card_area, fg_color="white", corner_radius=18, border_width=1, border_color=BORDER)
            frame.grid(row=i // 2, column=i % 2, padx=(2, 8) if i % 2 == 0 else (8, 2), pady=(8, 7), sticky="nsew")
            frame.grid_columnconfigure(0, weight=1)
            title = ctk.CTkFrame(frame, fg_color="transparent")
            title.grid(row=0, column=0, sticky="ew", padx=18, pady=(17, 9))
            title.grid_columnconfigure(1, weight=1)
            image = self._game_image(module.id)
            ctk.CTkLabel(title, text="" if image else module.name[:1], image=image, width=58, height=58, corner_radius=13,
                fg_color="transparent" if image else "#eaf0ff", font=(FONT, 25, "bold"), text_color=BLUE).grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 12))
            ctk.CTkLabel(title, text=module.name, font=(FONT, 18, "bold"), text_color=INK, anchor="w").grid(row=0, column=1, sticky="ew")
            platform = LOGIN_SITES.get(module.platform, (module.platform, ""))[0]
            ctk.CTkLabel(title, text=platform + " · 每日签到", font=(FONT, 12), text_color=MUTED, anchor="w").grid(row=1, column=1, sticky="ew")
            state = ctk.CTkLabel(title, text="待登录", fg_color="#fff2d8", text_color="#986800", width=81, height=26, corner_radius=13, font=(FONT, 11))
            state.grid(row=0, column=2, sticky="ne", padx=(5, 0))
            enabled = tk.BooleanVar(value=config.get(module.id, {}).get("enabled", True))
            ctk.CTkSwitch(title, text="启用", variable=enabled, font=(FONT, 11), text_color=MUTED, width=78,
                switch_width=29, switch_height=16, progress_color=BLUE, button_color="white", button_hover_color="#edf2fb", fg_color="#d8e0eb",
                command=lambda m=module, v=enabled: self.enable_module(m, v.get())).grid(row=1, column=2, sticky="e", padx=(5, 0))
            msg = tk.StringVar(value="登录后即可领取每日奖励")
            message = ctk.CTkLabel(frame, textvariable=msg, font=(FONT, 12), text_color="#52627c", anchor="w", justify="left", wraplength=420, height=36)
            message.grid(row=1, column=0, sticky="ew", padx=19, pady=(1, 10))
            frame.bind("<Configure>", lambda event, label=message: label.configure(wraplength=max(220, event.width - 42)), add="+")
            buttons = ctk.CTkFrame(frame, fg_color="transparent")
            buttons.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 17))
            self._button(buttons, "账号登录", lambda m=module: self.login(m), width=91).pack(side="left")
            self._button(buttons, "立即执行", lambda m=module: self.run_all([m.id], force=True), True, 91).pack(side="left", padx=(8, 0))
            text, command = ("任务与兑换", lambda m=module: self.gf2_options(m)) if module.id == "gf2" else ("官方社区 ↗", lambda m=module: webbrowser.open(m.site))
            ctk.CTkButton(buttons, text=text, command=command, width=98, height=34, corner_radius=9, font=(FONT, 12),
                fg_color="transparent", hover_color="#f0f4fb", text_color=MUTED).pack(side="right")
            self.cards[module.id] = (state, msg, enabled)

    def enable_module(self, module, enabled):
        self.settings.set_module(module.id, enabled=enabled)
        self.refresh()

    def refresh(self):
        snapshot = self.engine.snapshot()
        settings = self.settings.read()
        try:
            self.last_platforms = set(self.vault.platforms())
        except Exception:
            self.last_platforms = set()
        day = beijing_now().date().isoformat()
        complete = 0
        active = 0
        for module_id, (label, message, enabled) in self.cards.items():
            module = self.registry.modules[module_id]
            if not enabled.get():
                label.configure(text="已停用", fg_color="#edf0f5", text_color=MUTED)
                message.set("该游戏不参与一键或自动签到")
                continue
            active += 1
            record = snapshot.get("modules", {}).get(module_id, {})
            if snapshot.get("last_success", {}).get(module_id) == day:
                complete += 1
                label.configure(text="今日已完成", fg_color="#e3f5ec", text_color="#23764a")
                message.set(record.get("message", "今天已完成"))
            elif record.get("status") == "error" and record.get("time", "").startswith(day):
                label.configure(text="需要处理", fg_color="#ffebea", text_color="#b5453c")
                message.set(record.get("message", "执行未完成"))
            elif module.platform not in self.last_platforms or record.get("status") == "needs_login":
                label.configure(text="需要登录", fg_color="#fff5de", text_color="#9a6400")
                message.set(record.get("message", "点击登录，完成官方账号验证"))
            else:
                label.configure(text="已就绪", fg_color="#eaf0ff", text_color=BLUE)
                message.set("已保存登录状态，等待执行")
        self.summary.set(f"今日已完成 {complete} / {active} 款游戏")
        self.history.configure(state="normal")
        self.history.delete("1.0", "end")
        for item in reversed(snapshot.get("history", [])[-100:]):
            name = getattr(self.registry.modules.get(item.get("module_id")), "name", item.get("module_id", ""))
            when = item.get("time", "").replace("T", " ")[:19]
            self.history.insert("end", f"{when}  {name}  ·  {STATUS_NAMES.get(item.get('status'), item.get('status', ''))}\n{item.get('message', '')}\n")
            for detail in item.get("details", []):
                self.history.insert("end", f"  {detail}\n")
            self.history.insert("end", "\n")
        self.history.configure(state="disabled")
        if hasattr(self, "footer") and not self.busy:
            enabled = settings["auto_enabled"] or settings["background_enabled"]
            text = f"下次自动执行：{next_run().strftime('%m月%d日 %H:%M:%S')}（北京时间）" if enabled else "自动签到已关闭 · 可在设置中自行开启"
            if self.registry.errors:
                text += " · 部分扩展加载失败，请检查模块文件"
            self.footer.set(text)

    def run_all(self, ids=None, force=False, source="manual"):
        if self.busy:
            if source == "scheduled":
                self.pending_scheduled = True
            self.footer.set("当前任务仍在执行，请稍候")
            return
        self.busy = True
        self.run_button.configure(state="disabled")
        self.footer.set("正在处理已启用的游戏…")
        def work():
            try:
                results = self.engine.run(ids, force=force, source=source)
                self.queue.put(("done", results))
            except AlreadyRunning:
                self.queue.put(("notice", "另一个后台任务正在执行，本次未重复运行"))
                self.queue.put(("done", {}))
            except Exception as exc:
                self.queue.put(("notice", f"执行未完成：{type(exc).__name__}"))
                self.queue.put(("done", {}))
        threading.Thread(target=work, name="checkin-runner", daemon=False).start()

    def poll(self):
        try:
            for _ in range(100):
                try:
                    kind, value = self.queue.get_nowait()
                except queue.Empty:
                    break
                try:
                    self._handle_queue(kind, value)
                except Exception:
                    # Stale dialog callbacks must not stop the main event pump.
                    continue
            if not self.busy and time.monotonic() - self._last_idle_check > 2:
                self._last_idle_check = time.monotonic()
                try:
                    stamp = (self.data_dir / "state.json").stat().st_mtime_ns
                except OSError:
                    stamp = None
                if stamp != self._state_stamp:
                    self._state_stamp = stamp
                    self.refresh()
        finally:
            if not self._closing:
                try:
                    self._poll_after = self.root.after(150, self.poll)
                except tk.TclError:
                    self._closing = True

    def _handle_queue(self, kind, value):
        if kind == "scheduled":
            self.run_all(source="scheduled")
        elif kind == "event":
            module = self.registry.modules.get(value["module_id"])
            self.footer.set(f"{getattr(module, 'name', '')}：{value['message']}")
            if value["module_id"] in self.cards:
                self.cards[value["module_id"]][1].set(value["message"])
                if value["status"] == "running":
                    self.cards[value["module_id"]][0].configure(text="进行中", fg_color="#eaf0ff", text_color=BLUE)
        elif kind == "done":
            self.busy = False
            self.run_button.configure(state="normal")
            self.refresh()
            needs = [self.registry.modules[k].name for k, r in value.items() if r.status == "needs_login"]
            if needs:
                self.footer.set("需要你登录：" + "、".join(needs) + "，请点击对应游戏的“登录”")
                self.root.bell()
            if self.pending_scheduled:
                self.pending_scheduled = False
                self.root.after(50, lambda: self.run_all(source="scheduled"))
        elif kind == "notice":
            self.footer.set(value)
        elif kind == "call":
            try:
                value()
            except tk.TclError:
                pass

    def toggle_auto(self):
        self.settings.update({"auto_enabled": self.auto.get()})
        self.refresh()

    def _check_background_state(self):
        generation = self._background_generation
        def work():
            try:
                exists = background_task_exists(self.project_dir)
                def update():
                    if generation != self._background_generation:
                        return
                    saved = self.settings.read().get("background_enabled", False)
                    if saved and not exists:
                        self.settings.update({"background_enabled": False})
                        self.background.set(False)
                        self.refresh()
                    if exists and saved:
                        self.background_hint.set("后台任务已启用，助手窗口无需保持打开。")
                    elif exists:
                        self.background_hint.set("已安装后台任务，当前自动运行已关闭。")
                    else:
                        self.background_hint.set("尚未开启；开启后交给 Windows 在后台执行。")
                self.queue.put(("call", update))
            except Exception:
                self.queue.put(("call", lambda: self.background_hint.set("暂时无法确认后台任务，请稍后再试。")))
        threading.Thread(target=work, name="background-state-check", daemon=True).start()

    def toggle_background(self):
        if self.background_busy:
            self.background.set(self.settings.read().get("background_enabled", False))
            return
        requested, catch_up = self.background.get(), self.catch_up.get()
        previous = self.settings.read().get("background_enabled", False)
        self.background_busy = True
        self._background_generation += 1
        self.background_switch.configure(state="disabled")
        self.catch_up_switch.configure(state="disabled")
        self.background_hint.set("正在更新 Windows 后台任务…")
        def work():
            error = None
            try:
                if requested:
                    register_background_task(self.project_dir, catch_up=catch_up)
                    if not background_task_exists(self.project_dir):
                        raise RuntimeError("后台任务尚未创建成功")
                else:
                    remove_background_task(self.project_dir)
                    if background_task_exists(self.project_dir):
                        raise RuntimeError("后台任务尚未关闭成功")
                self.settings.update({"background_enabled": requested})
            except Exception as exc:
                error = self._friendly_error(exc)
            def finish():
                self.background_busy = False
                self.background_switch.configure(state="normal")
                self.catch_up_switch.configure(state="normal")
                self.background.set(previous if error else requested)
                self.background_hint.set(error or ("后台任务已启用，助手窗口无需保持打开。" if requested else "后台任务已关闭；可随时重新开启。"))
                self.refresh()
                if error:
                    messagebox.showerror("设置未完成", error + "\n仍可使用程序运行时自动签到。", parent=self.root)
            self.queue.put(("call", finish))
        threading.Thread(target=work, name="background-task-update", daemon=True).start()

    def toggle_catch_up(self):
        requested = self.catch_up.get()
        previous = self.settings.read().get("catch_up_on_start", True)
        if not self.background.get():
            self.settings.update({"catch_up_on_start": requested})
            return
        if self.background_busy:
            self.catch_up.set(previous)
            return
        self.background_busy = True
        self._background_generation += 1
        self.background_switch.configure(state="disabled")
        self.catch_up_switch.configure(state="disabled")
        def work():
            error = None
            try:
                register_background_task(self.project_dir, catch_up=requested)
                if not background_task_exists(self.project_dir):
                    raise RuntimeError("后台任务尚未创建成功")
                self.settings.update({"catch_up_on_start": requested})
            except Exception as exc:
                error = self._friendly_error(exc)
            def finish():
                self.background_busy = False
                self.background_switch.configure(state="normal")
                self.catch_up_switch.configure(state="normal")
                self.catch_up.set(previous if error else requested)
                if error:
                    messagebox.showerror("设置未完成", error, parent=self.root)
            self.queue.put(("call", finish))
        threading.Thread(target=work, name="catchup-task-update", daemon=True).start()

    @staticmethod
    def _friendly_error(exc):
        text = str(exc).strip()
        if not text or any(word in text.lower() for word in ("token", "authorization", "cookie", "eyj", "traceback", "httpconnectionpool")):
            return "登录状态尚未通过检查，请完成官方验证后重试。"
        return text[:220]

    def login(self, module):
        if self.login_job:
            messagebox.showinfo("登录进行中", "请先完成或取消当前登录。", parent=self.root)
            return
        if module.platform == "tajiduo":
            self.sms_tajiduo(module)
            return
        dialog = ctk.CTkToplevel(self.root)
        dialog.title("登录 · " + module.name)
        dialog.geometry("620x330")
        dialog.transient(self.root)
        text = tk.StringVar(value="将打开官方页面，请自行登录；密码和验证码无需发给任何人。")
        ttk.Label(dialog, text=module.name, font=(FONT, 20, "bold"), padding=20).pack(anchor="w")
        ttk.Label(dialog, textvariable=text, wraplength=500, padding=(20, 0, 20, 20)).pack(fill="x")
        buttons = ttk.Frame(dialog, padding=20)
        buttons.pack(fill="x")
        def enqueue(fn):
            self.queue.put(("call", fn))
        def success(credential, message):
            if job.cancel.is_set():
                return
            self.vault.set(module.platform, credential)
            self.engine.invalidate_platform(module.platform)
            def update():
                if not dialog.winfo_exists():
                    return
                text.set(message + "，已加密保存在本机")
                self.refresh()
                dialog.after(1300, lambda: dialog.destroy() if dialog.winfo_exists() else None)
            enqueue(update)
        def finish():
            enqueue(lambda: setattr(self, "login_job", None) if self.login_job is job else None)
        def set_text(value):
            enqueue(lambda: text.set(value) if dialog.winfo_exists() else None)
        self.login_job = BrowserLogin(module.platform, module, self.settings.options_for(module.id), set_text, success, finish)
        job = self.login_job
        ttk.Button(buttons, text="检查登录", style="Accent.TButton", command=job.check.set).pack(side="left")
        def close():
            job.cancel.set()
            dialog.destroy()
        ttk.Button(buttons, text="取消", command=close).pack(side="left", padx=8)
        if module.platform == "gf2":
            ttk.Button(buttons, text="从现有工具导入", command=lambda: (close(), self.import_gf2())).pack(side="right")
        elif module.platform == "tajiduo":
            ttk.Button(buttons, text="改用短信登录", command=lambda: (close(), self.sms_tajiduo(module))).pack(side="right")
        dialog.protocol("WM_DELETE_WINDOW", close)
        job.start()

    def import_gf2(self):
        downloads = Path.home() / "Downloads"
        path = filedialog.askopenfilename(title="选择 gf2gacha 的 config.yaml", initialdir=str(downloads if downloads.is_dir() else Path.home()), filetypes=[("工具配置", "*.yaml *.yml"), ("所有文件", "*.*")])
        if not path:
            return
        module = self.registry.modules.get("gf2")
        if not module:
            return
        self.footer.set("正在检查已保存的少前2社区登录…")
        def work():
            try:
                credential, options = import_gf2_config(path)
                ctx = RunContext(module.id, credential, {**self.settings.options_for(module.id), **options})
                try:
                    result = module.validate(ctx)
                finally:
                    ctx.session.close()
                if result.status not in SUCCESS_STATUSES:
                    raise ValueError(result.message)
                self.vault.set(module.platform, credential)
                self.engine.invalidate_platform(module.platform)
                if options:
                    self.settings.set_module(module.id, options={**self.settings.options_for(module.id), **options})
                self.queue.put(("call", self.refresh))
                self.queue.put(("notice", "少前2社区登录已验证并加密保存，无需启动游戏"))
            except Exception as exc:
                self.queue.put(("notice", f"少前2导入未完成：{type(exc).__name__}，可改用官方网页登录"))
        threading.Thread(target=work, daemon=True).start()

    def sms_tajiduo(self, module):
        existing = getattr(self, "_sms_dialog", None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            return
        api = importlib.import_module(module.__class__.__module__)
        dialog = ctk.CTkToplevel(self.root)
        self._sms_dialog = dialog
        dialog.title("塔吉多 · 短信登录")
        dialog.geometry("500x450")
        dialog.transient(self.root)
        dialog.configure(fg_color=BG)
        box = ctk.CTkFrame(dialog, fg_color="white", corner_radius=18)
        box.pack(fill="both", expand=True, padx=20, pady=20)
        ctk.CTkLabel(box, text="短信登录", text_color=INK, font=(FONT, 21, "bold")).pack(anchor="w", padx=24, pady=(18, 8))
        ctk.CTkLabel(box, text="手机号", text_color=MUTED, font=(FONT, 12)).pack(anchor="w", padx=24)
        phone = ctk.CTkEntry(box, height=38, corner_radius=10, border_color=BORDER, font=(FONT, 14), placeholder_text="11 位手机号")
        phone.pack(fill="x", padx=24, pady=(4, 10))
        ctk.CTkLabel(box, text="短信验证码", text_color=MUTED, font=(FONT, 12)).pack(anchor="w", padx=24)
        code = ctk.CTkEntry(box, height=38, corner_radius=10, border_color=BORDER, font=(FONT, 14), placeholder_text="收到后填写")
        code.pack(fill="x", padx=24, pady=(4, 6))
        text = tk.StringVar(value="使用绑定异环角色的手机号。登录后将自动保存并续期。")
        ctk.CTkLabel(box, textvariable=text, text_color=MUTED, font=(FONT, 12), wraplength=390,
            anchor="w", justify="left", height=48).pack(fill="x", padx=24, pady=(0, 8))
        device, busy, cancelled = api.generate_device_id(), threading.Event(), threading.Event()
        def close():
            cancelled.set()
            self._sms_dialog = None
            if dialog.winfo_exists():
                dialog.destroy()
        def update(message):
            if dialog.winfo_exists():
                text.set(message)
        def execute(is_login):
            if busy.is_set():
                return
            mobile, otp = phone.get().strip(), code.get().strip()
            if not re_phone(mobile):
                text.set("请输入正确的 11 位手机号")
                return
            busy.set()
            text.set("正在验证登录…" if is_login else "正在请求短信验证码…")
            def work():
                try:
                    if is_login:
                        credential = api.login_sms(mobile, otp, device)
                        if cancelled.is_set():
                            return
                        ctx = RunContext(module.id, credential, self.settings.options_for(module.id))
                        try:
                            result = module.validate(ctx)
                        finally:
                            ctx.session.close()
                        if result.status not in SUCCESS_STATUSES:
                            raise ValueError(result.message)
                        if cancelled.is_set():
                            return
                        self.vault.set(module.platform, credential)
                        self.engine.invalidate_platform(module.platform)
                        self.queue.put(("call", lambda: (close(), self.refresh())))
                        self.queue.put(("notice", "塔吉多登录已验证并加密保存，可以执行异环签到"))
                    else:
                        api.send_sms(mobile, device)
                        self.queue.put(("call", lambda: update("验证码已发送，请查收短信")))
                except Exception as exc:
                    message = self._friendly_error(exc)
                    self.queue.put(("call", lambda message=message: update(message)))
                finally:
                    busy.clear()
            threading.Thread(target=work, name="tajiduo-sms-login", daemon=True).start()
        buttons = ctk.CTkFrame(box, fg_color="transparent")
        buttons.pack(side="bottom", fill="x", padx=24, pady=(0, 21))
        self._button(buttons, "发送验证码", lambda: execute(False), width=112).pack(side="left")
        self._button(buttons, "提交登录", lambda: execute(True), True, 105).pack(side="right")
        self._button(buttons, "取消", close, width=66).pack(side="right", padx=7)
        dialog.protocol("WM_DELETE_WINDOW", close)

    def gf2_options(self, module):
        dialog = ctk.CTkToplevel(self.root)
        dialog.title("少前2 · 每日任务与兑换")
        dialog.geometry("620x440")
        box = ttk.Frame(dialog, padding=24)
        box.pack(fill="both", expand=True)
        options = self.settings.options_for(module.id)
        daily = tk.BooleanVar(value=options.get("daily_tasks", True))
        exchange = tk.BooleanVar(value=options.get("exchange", True))
        ttk.Checkbutton(box, text="完成社区每日任务（浏览、点赞、分享）", variable=daily).pack(anchor="w", pady=8)
        ttk.Checkbutton(box, text="使用社区积分兑换物品", variable=exchange).pack(anchor="w", pady=8)
        ttk.Label(box, text="兑换优先顺序（用逗号分隔；* 表示其余可兑换物品）", wraplength=490).pack(anchor="w", pady=(18, 8))
        order = ttk.Entry(box)
        order.insert(0, ", ".join(str(x) for x in options.get("exchange_priority", ["基原信息核", "情报拼图", "*"])))
        order.pack(fill="x")
        ttk.Label(box, text="按实时积分、库存及兑换限额处理。积分不足时先兑换排在前面的物品。", wraplength=490, foreground=MUTED).pack(anchor="w", pady=16)
        def save():
            priority = [x.strip() for x in order.get().replace("，", ",").split(",") if x.strip()]
            self.settings.set_module(module.id, options={**options, "daily_tasks": daily.get(), "exchange": exchange.get(), "exchange_priority": priority or ["*"]})
            self.engine.invalidate_platform(module.platform)
            self.refresh()
            dialog.destroy()
        ttk.Button(box, text="保存设置", style="Accent.TButton", command=save).pack(anchor="e", pady=12)

    def manage_games(self):
        dialog = ctk.CTkToplevel(self.root)
        dialog.title("管理游戏")
        dialog.geometry("540x560")
        box = ttk.Frame(dialog, padding=22)
        box.pack(fill="both", expand=True)
        ttk.Label(box, text="勾选要显示的游戏；隐藏时同时停用。", foreground=MUTED).pack(anchor="w", pady=(0, 14))
        config = self.settings.read().get("modules", {})
        values = {}
        for module in self.registry.modules.values():
            var = tk.BooleanVar(value=not config.get(module.id, {}).get("hidden", False))
            values[module.id] = var
            ttk.Checkbutton(box, text=module.name, variable=var).pack(anchor="w", pady=7)
        def save():
            for module_id, var in values.items():
                self.settings.set_module(module_id, hidden=not var.get(), enabled=var.get() and config.get(module_id, {}).get("enabled", True))
            self._build_cards()
            self.refresh()
            dialog.destroy()
        def install():
            path = filedialog.askopenfilename(title="选择要导入的游戏模块", filetypes=[("游戏模块", "*.py")], parent=dialog)
            if not path:
                return
            target = self.project_dir / "plugins" / Path(path).name
            if target.exists():
                messagebox.showinfo("模块已存在", "同名模块已存在，请先在文件夹中管理对应模块。", parent=dialog)
                return
            shutil.copy2(path, target)
            new_registry = Registry().discover(self.project_dir / "adapters", self.project_dir / "plugins")
            self.registry = self.engine.registry = new_registry
            self._build_cards()
            self.refresh()
            dialog.destroy()
        ttk.Button(box, text="导入游戏模块", command=install).pack(anchor="w", pady=(18, 8))
        ttk.Button(box, text="保存", style="Accent.TButton", command=save).pack(anchor="e", pady=10)

    def close(self):
        if self.busy:
            self.footer.set("当前任务正在执行，完成后再关闭可保留完整结果")
            return
        if self.login_job:
            self.login_job.cancel.set()
        self._closing = True
        self.timer.stop()
        if self._poll_after:
            try:
                self.root.after_cancel(self._poll_after)
            except tk.TclError:
                pass
        self.root.destroy()


def re_phone(value):
    return value.isdigit() and len(value) == 11 and value.startswith("1")
