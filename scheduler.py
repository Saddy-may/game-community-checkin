"""Daily 00:00:10 Beijing scheduling and opt-in Windows background tasks."""
from __future__ import annotations

from datetime import datetime, time as datetime_time, timedelta
import getpass
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from typing import Callable
import xml.etree.ElementTree as ET

from checkin_core import BEIJING, beijing_now


def daily_target(now: datetime | None = None) -> datetime:
    local = (now or beijing_now()).astimezone(BEIJING)
    return datetime.combine(local.date(), datetime_time(0, 0, 10), BEIJING)


def should_run(now: datetime, last_trigger_date: str | None = None) -> bool:
    local = now.astimezone(BEIJING)
    return local >= daily_target(local) and local.date().isoformat() != last_trigger_date


def next_run(now: datetime | None = None) -> datetime:
    local = (now or beijing_now()).astimezone(BEIJING)
    target = daily_target(local)
    return target if local < target else target + timedelta(days=1)


class DailyScheduler:
    """Call once each local day, with a one-second clock check; never runs UI code."""
    def __init__(self, callback: Callable[[], None], enabled: Callable[[], bool],
                 on_error: Callable[[str], None] | None = None,
                 catch_up: Callable[[], bool] | None = None) -> None:
        self.callback = callback
        self.enabled = enabled
        self.on_error = on_error
        self.catch_up = catch_up or (lambda: True)
        self.last_trigger_date: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._start_time: datetime | None = None
        self._enabled_since: datetime | None = None

    def tick(self, now: datetime | None = None) -> bool:
        now = (now or beijing_now()).astimezone(BEIJING)
        if self._start_time is None:
            self._start_time = now
        if not self.enabled():
            self._enabled_since = None
            return False
        if self._enabled_since is None:
            self._enabled_since = now
        if not should_run(now, self.last_trigger_date):
            return False
        if not self.catch_up() and self._enabled_since > daily_target(now):
            self.last_trigger_date = now.date().isoformat()
            return False
        self.last_trigger_date = now.date().isoformat()
        self.callback()
        return True

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._start_time = beijing_now()
        def loop():
            while not self._stop.is_set():
                try:
                    self.tick()
                except Exception as exc:
                    if self.on_error:
                        self.on_error(str(exc))
                self._stop.wait(0.5)
        self._thread = threading.Thread(target=loop, name="daily-checkin-clock", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()


def task_name(project_dir: str | Path) -> str:
    digest = hashlib.sha256(str(Path(project_dir).resolve()).casefold().encode()).hexdigest()[:10]
    return f"CommunityCheckin-{digest}"


def _windows_user() -> str:
    domain = os.environ.get("USERDOMAIN", "")
    name = getpass.getuser()
    return f"{domain}\\{name}" if domain else name


def task_xml(project_dir: str | Path, python_executable: str | Path | None = None,
             now: datetime | None = None, user: str | None = None, catch_up: bool = True) -> str:
    """Build XML only; no system changes. Program must support --headless --scheduled."""
    path = Path(project_dir).resolve()
    executable = str(Path(python_executable or sys.executable).resolve())
    if not getattr(sys, "frozen", False) and Path(executable).name.casefold() == "python.exe":
        pythonw = Path(executable).with_name("pythonw.exe")
        if pythonw.exists():
            executable = str(pythonw)
    if getattr(sys, "frozen", False):
        arguments = "--headless --scheduled"
    else:
        arguments = subprocess.list2cmdline([str(path / "app.py"), "--headless", "--scheduled"])
    ns = "http://schemas.microsoft.com/windows/2004/02/mit/task"
    ET.register_namespace("", ns)
    def element(parent, tag, text=None, **attrs):
        item = ET.SubElement(parent, "{" + ns + "}" + tag, attrs)
        if text is not None:
            item.text = str(text)
        return item
    root = ET.Element("{" + ns + "}Task", {"version": "1.4"})
    info = element(root, "RegistrationInfo")
    element(info, "Description", "游戏社区签到助手：每天北京时间 00:00:10，及登录后补跑当天任务。仅当前 Windows 用户。")
    triggers = element(root, "Triggers")
    calendar = element(triggers, "CalendarTrigger")
    element(calendar, "StartBoundary", daily_target(now).isoformat(timespec="seconds"))
    element(calendar, "Enabled", "true")
    daily = element(calendar, "ScheduleByDay")
    element(daily, "DaysInterval", "1")
    identity = user or _windows_user()
    if catch_up:
        logon = element(triggers, "LogonTrigger")
        element(logon, "Enabled", "true")
        element(logon, "Delay", "PT30S")
        element(logon, "UserId", identity)
    principals = element(root, "Principals")
    principal = element(principals, "Principal", id="Author")
    element(principal, "UserId", identity)
    element(principal, "LogonType", "InteractiveToken")
    element(principal, "RunLevel", "LeastPrivilege")
    settings = element(root, "Settings")
    for tag, value in [
        ("MultipleInstancesPolicy", "IgnoreNew"),
        ("DisallowStartIfOnBatteries", "false"),
        ("StopIfGoingOnBatteries", "false"),
        ("AllowHardTerminate", "true"),
        ("StartWhenAvailable", "true" if catch_up else "false"),
        ("RunOnlyIfNetworkAvailable", "false"),
        ("AllowStartOnDemand", "true"),
        ("Enabled", "true"),
        ("Hidden", "false"),
        ("RunOnlyIfIdle", "false"),
        ("WakeToRun", "false"),
        ("ExecutionTimeLimit", "PT30M"),
        ("Priority", "7"),
    ]:
        element(settings, tag, value)
    restart = element(settings, "RestartOnFailure")
    element(restart, "Interval", "PT3M")
    element(restart, "Count", "3")
    actions = element(root, "Actions", Context="Author")
    action = element(actions, "Exec")
    element(action, "Command", executable)
    element(action, "Arguments", arguments)
    element(action, "WorkingDirectory", str(path))
    return '<?xml version="1.0" encoding="UTF-16"?>\n' + ET.tostring(root, encoding="unicode")


def _schtasks(args: list[str], timeout: int = 25) -> subprocess.CompletedProcess:
    if os.name != "nt":
        raise RuntimeError("后台运行功能需要 Windows")
    return subprocess.run(["schtasks.exe", *args], capture_output=True,
                          creationflags=subprocess.CREATE_NO_WINDOW, timeout=timeout)


def register_background_task(project_dir: str | Path, python_executable: str | Path | None = None,
                             catch_up: bool = True) -> str:
    xml = task_xml(project_dir, python_executable, catch_up=catch_up)
    descriptor, temp_path = tempfile.mkstemp(prefix="community-checkin-", suffix=".xml")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(xml.encode("utf-16"))
        result = _schtasks(["/Create", "/TN", task_name(project_dir), "/XML", temp_path, "/F"])
        if result.returncode:
            raise RuntimeError("无法开启 Windows 后台签到，请确认当前用户有创建计划任务的权限")
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    return task_name(project_dir)


def remove_background_task(project_dir: str | Path) -> None:
    if not background_task_exists(project_dir):
        return
    result = _schtasks(["/Delete", "/TN", task_name(project_dir), "/F"])
    if result.returncode:
        raise RuntimeError("无法关闭 Windows 后台签到，请在计划任务中检查本程序的任务")


def background_task_exists(project_dir: str | Path) -> bool:
    if os.name != "nt":
        return False
    result = _schtasks(["/Query", "/TN", task_name(project_dir)])
    return result.returncode == 0

