"""Plugin contracts, encrypted local storage, and one-shot check-in execution."""
from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from typing import Any, Callable


BEIJING = timezone(timedelta(hours=8))
SUCCESS_STATUSES = {"success", "already_signed"}


def beijing_now() -> datetime:
    return datetime.now(BEIJING)


def today_key(now: datetime | None = None) -> str:
    return (now or beijing_now()).astimezone(BEIJING).date().isoformat()


class AuthRequired(Exception):
    """An adapter needs the user to log in again."""


NeedLoginError = AuthRequired


class CredentialUnavailable(AuthRequired):
    """Saved credentials belong to another Windows profile or are unreadable."""


class AlreadyRunning(RuntimeError):
    pass


@dataclass
class RunResult:
    status: str
    message: str
    details: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status in SUCCESS_STATUSES


@dataclass
class RunContext:
    module_id: str
    credential: dict[str, Any]
    options: dict[str, Any]
    log: Callable[[str], None] = lambda message: None
    save_credential: Callable[[dict[str, Any]], None] = lambda value: None
    session: Any = None

    def __post_init__(self) -> None:
        if self.session is None:
            import requests
            self.session = requests.Session()
            # Adapters should keep credentials in headers; never include them in URLs.
            self.session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36"})


class Registry:
    def __init__(self) -> None:
        self.modules: dict[str, Any] = {}
        self.errors: list[str] = []

    def register(self, module: Any) -> None:
        for name in ("id", "name", "platform", "site"):
            if not isinstance(getattr(module, name, None), str):
                raise ValueError(f"游戏模块缺少 {name}")
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", module.id):
            raise ValueError("游戏模块 id 必须是英文、数字、下划线或连字符")
        if not callable(getattr(module, "run", None)):
            raise ValueError(f"{module.id} 缺少 run(context)")
        if module.id in self.modules:
            raise ValueError(f"游戏模块 id 重复：{module.id}")
        self.modules[module.id] = module

    def discover(self, adapters_dir: str | Path, plugins_dir: str | Path | None = None) -> "Registry":
        """Load explicitly installed Python modules. Plugins are trusted local code."""
        for directory in (adapters_dir, plugins_dir):
            if directory is None:
                continue
            path = Path(directory)
            if not path.exists():
                continue
            for file in sorted(path.glob("*.py")):
                if file.name.startswith("_") or file.stem in {"common", "base"}:
                    continue
                try:
                    import hashlib
                    unique = hashlib.sha256(str(file.resolve()).encode()).hexdigest()[:12]
                    spec = importlib.util.spec_from_file_location(f"checkin_plugin_{file.stem}_{unique}", file)
                    if spec is None or spec.loader is None:
                        raise ImportError("无法加载模块")
                    module = importlib.util.module_from_spec(spec)
                    import sys
                    sys.modules[spec.name] = module
                    spec.loader.exec_module(module)
                    candidates = getattr(module, "MODULES", [])
                    for candidate in candidates:
                        self.register(candidate)
                except Exception as exc:
                    # Report an individual plugin failure without losing other games.
                    self.errors.append(f"{file.name}：{type(exc).__name__}：{exc}")
        return self


_THREAD_LOCKS: dict[str, threading.RLock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


class FileRunLock:
    """A same-user interprocess lock that is released even if a process exits."""
    def __init__(self, path: str | Path, timeout: float = 0) -> None:
        self.path = Path(path)
        self.timeout = timeout
        self._file = None
        with _THREAD_LOCKS_GUARD:
            self._thread_lock = _THREAD_LOCKS.setdefault(str(self.path.resolve()), threading.RLock())

    def __enter__(self) -> "FileRunLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout
        if not self._thread_lock.acquire(timeout=max(0, self.timeout)):
            raise AlreadyRunning("另一个任务正在运行，请稍候")
        try:
            self._file = self.path.open("a+b")
            self._file.seek(0, os.SEEK_END)
            if self._file.tell() == 0:
                self._file.write(b"0")
                self._file.flush()
            while True:
                try:
                    self._file.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return self
                except OSError:
                    if time.monotonic() >= deadline:
                        raise AlreadyRunning("另一个任务正在运行，请稍候") from None
                    time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        except BaseException:
            if self._file is not None:
                self._file.close()
                self._file = None
            self._thread_lock.release()
            raise

    def __exit__(self, *args) -> None:
        try:
            if self._file is not None:
                self._file.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
                self._file.close()
        finally:
            self._file = None
            self._thread_lock.release()


def _atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


class JsonStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("JSON 根节点必须是对象")
            return value
        except (ValueError, UnicodeDecodeError) as exc:
            raise RuntimeError(f"无法读取 {self.path.name}，请保留文件并从备份恢复") from exc

    def read(self) -> dict[str, Any]:
        with FileRunLock(self.lock_path, timeout=5):
            return self._read()

    def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        return self.modify(lambda data: data.update(patch))

    def modify(self, mutator: Callable[[dict[str, Any]], Any]) -> dict[str, Any]:
        with FileRunLock(self.lock_path, timeout=5):
            value = self._read()
            mutator(value)
            _atomic_write(self.path, json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8"))
            return value


class SettingsStore(JsonStore):
    DEFAULTS = {
        "version": 1,
        "auto_enabled": False,
        "background_enabled": False,
        "catch_up_on_start": True,
        "notify_errors": True,
        "modules": {},
    }

    def __init__(self, data_dir: str | Path) -> None:
        super().__init__(Path(data_dir) / "settings.json")

    def read(self) -> dict[str, Any]:
        return {**self.DEFAULTS, **super().read()}

    def set_module(self, module_id: str, **settings: Any) -> dict[str, Any]:
        def change(data):
            current = data.setdefault("modules", {}).setdefault(module_id, {"enabled": True, "options": {}})
            current.update(settings)
        self.modify(change)
        return self.read()

    def module_settings(self, module_id: str) -> dict[str, Any]:
        data = self.read().get("modules", {}).get(module_id, {})
        return {"enabled": True, "options": {}, **data}

    def options_for(self, module_id: str, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
        saved = self.module_settings(module_id).get("options") or {}
        return {**(defaults or {}), **saved}


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi(raw: bytes, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        raise RuntimeError("登录凭据加密需要 Windows；不会使用明文保存")
    buffer = ctypes.create_string_buffer(raw)
    source = _DATA_BLOB(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = _DATA_BLOB()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        operation = crypt32.CryptUnprotectData
        operation.argtypes = [ctypes.POINTER(_DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DATA_BLOB)]
        ok = operation(ctypes.byref(source), None, None, None, None, 0x1, ctypes.byref(target))
    else:
        operation = crypt32.CryptProtectData
        operation.argtypes = [ctypes.POINTER(_DATA_BLOB), wintypes.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DATA_BLOB)]
        ok = operation(ctypes.byref(source), "Community Check-in local credentials", None, None, None, 0x1, ctypes.byref(target))
    operation.restype = wintypes.BOOL
    if not ok:
        if decrypt:
            raise CredentialUnavailable("无法在当前 Windows 用户下解密已有登录信息，请重新登录")
        raise RuntimeError("Windows 无法加密登录信息")
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(target.pbData, ctypes.c_void_p))


class CredentialVault:
    MAGIC = b"COMMUNITY_CHECKIN_DPAPI_V1\x00"

    def __init__(self, data_dir: str | Path) -> None:
        self.path = Path(data_dir) / "credentials.bin"
        self.lock_path = self.path.with_suffix(".lock")

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        raw = self.path.read_bytes()
        if not raw.startswith(self.MAGIC):
            raise CredentialUnavailable("登录信息格式不正确，请重新登录")
        try:
            value = json.loads(_dpapi(raw[len(self.MAGIC):], decrypt=True))
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except (ValueError, UnicodeDecodeError):
            raise CredentialUnavailable("无法读取登录信息，请重新登录") from None

    def get(self, platform: str) -> dict[str, Any]:
        with FileRunLock(self.lock_path, timeout=5):
            value = self._read().get(platform, {})
            return dict(value) if isinstance(value, dict) else {}

    def set(self, platform: str, credential: dict[str, Any]) -> None:
        if not isinstance(credential, dict):
            raise TypeError("登录信息必须为字典")
        with FileRunLock(self.lock_path, timeout=5):
            recover = False
            try:
                value = self._read()
            except CredentialUnavailable:
                # A copied vault cannot be decrypted on a new PC/Windows user.
                # Only an explicit successful login reaches set(); preserve the
                # old encrypted file, then establish this user's new vault.
                value = {}
                recover = True
            value[platform] = credential
            raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
            encrypted = self.MAGIC + _dpapi(raw)
            backup = None
            if recover and self.path.exists():
                import secrets
                suffix = beijing_now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
                backup = self.path.with_name(f"credentials.unreadable-{suffix}.bin")
                os.replace(self.path, backup)
            try:
                _atomic_write(self.path, encrypted)
            except BaseException:
                if backup is not None and not self.path.exists():
                    os.replace(backup, self.path)
                raise

    def delete(self, platform: str) -> None:
        with FileRunLock(self.lock_path, timeout=5):
            value = self._read()
            value.pop(platform, None)
            _atomic_write(self.path, self.MAGIC + _dpapi(json.dumps(value, ensure_ascii=False).encode("utf-8")))

    def platforms(self) -> list[str]:
        with FileRunLock(self.lock_path, timeout=5):
            return list(self._read())


def _secret_strings(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [secret for child in value.values() for secret in _secret_strings(child)]
    if isinstance(value, (list, tuple)):
        return [secret for child in value for secret in _secret_strings(child)]
    return [value] if isinstance(value, str) and len(value) >= 4 else []


def redact(message: Any, credentials: Any = None) -> str:
    text = str(message)
    for secret in sorted(_secret_strings(credentials), key=len, reverse=True):
        text = text.replace(secret, "[已隐藏]")
    text = re.sub(r"(?i)((?:authorization|access[_-]?token|refresh[_-]?token|web[_-]?token|cookie[_-]?token|password|cookie|cred)\s*[=:]\s*)[^\s,;]+", r"\1[已隐藏]", text)
    text = re.sub(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", "[已隐藏]", text)
    return text[:2000]


class CheckinEngine:
    def __init__(self, registry: Registry, settings: SettingsStore, vault: CredentialVault,
                 data_dir: str | Path, on_event: Callable[[dict[str, Any]], None] | None = None) -> None:
        self.registry = registry
        self.settings = settings
        self.vault = vault
        self.data_dir = Path(data_dir)
        self.state = JsonStore(self.data_dir / "state.json")
        self.on_event = on_event

    def snapshot(self) -> dict[str, Any]:
        return self.state.read()

    def invalidate_platform(self, platform: str) -> None:
        """A user changed account/login: recheck affected games, retaining history."""
        affected = [module.id for module in self.registry.modules.values() if module.platform == platform]
        def change(data):
            revisions = data.setdefault("credential_revision", {})
            revisions[platform] = int(revisions.get(platform, 0)) + 1
            for module_id in affected:
                data.setdefault("last_success", {}).pop(module_id, None)
                data.setdefault("modules", {}).pop(module_id, None)
        self.state.modify(change)

    def _emit(self, module_id: str, message: str, status: str = "running", credential=None) -> None:
        event = {"time": beijing_now().isoformat(timespec="seconds"), "module_id": module_id,
                 "status": status, "message": redact(message, credential)}
        if self.on_event:
            try:
                self.on_event(event)
            except Exception:
                pass

    def _record(self, module_id: str, result: RunResult, day: str, source: str,
                platform: str, credential_revision: int) -> None:
        record = {"status": result.status, "message": result.message, "details": result.details,
                  "time": beijing_now().isoformat(timespec="seconds"), "source": source}
        def change(data):
            # A background operation using the old login must not mark the new
            # account as completed when the user changes account concurrently.
            if data.get("credential_revision", {}).get(platform, 0) != credential_revision:
                result.status = "skipped"
                result.message = "登录信息已更新，请重新执行该游戏"
                result.details = []
                record.update(status=result.status, message=result.message, details=[])
                data.setdefault("last_success", {}).pop(module_id, None)
            data.setdefault("modules", {})[module_id] = record
            if result.ok:
                data.setdefault("last_success", {})[module_id] = day
            history = data.setdefault("history", [])
            history.append({"module_id": module_id, **record})
            data["history"] = history[-500:]
        self.state.modify(change)

    def run(self, module_ids: list[str] | None = None, force: bool = False,
            source: str = "manual") -> dict[str, RunResult]:
        output: dict[str, RunResult] = {}
        with FileRunLock(self.data_dir / "running.lock", timeout=0):
            settings = self.settings.read()
            day = today_key()
            ids = list(self.registry.modules) if module_ids is None else list(dict.fromkeys(module_ids))
            for module_id in ids:
                module = self.registry.modules.get(module_id)
                if module is None:
                    output[module_id] = RunResult("error", "未找到游戏模块")
                    continue
                module_settings = {"enabled": True, "options": {}, **settings.get("modules", {}).get(module_id, {})}
                if not module_settings["enabled"]:
                    output[module_id] = RunResult("skipped", "此游戏已停用")
                    continue
                state = self.snapshot()
                credential_revision = int(state.get("credential_revision", {}).get(module.platform, 0))
                if not force and state.get("last_success", {}).get(module_id) == day:
                    result = RunResult("already_signed", "今天已完成")
                    output[module_id] = result
                    self._emit(module_id, result.message, result.status)
                    continue
                credential: dict[str, Any] = {}
                context = None
                try:
                    credential = self.vault.get(module.platform)
                    self._emit(module_id, "正在执行", credential=credential)
                    def save(value, platform=module.platform):
                        if not isinstance(value, dict):
                            raise TypeError("更新后的登录信息必须是字典")
                        if self.snapshot().get("credential_revision", {}).get(platform, 0) != credential_revision:
                            raise AuthRequired("登录信息已更新，请重新执行该游戏")
                        value = dict(value)
                        self.vault.set(platform, value)
                        if context is not None:
                            context.credential.clear()
                            context.credential.update(value)
                    options = {**getattr(module, "option_defaults", {}), **dict(module_settings.get("options") or {})}
                    context = RunContext(module_id, credential, options,
                                         lambda msg: self._emit(module_id, msg, credential=credential), save)
                    result = module.run(context)
                    if not isinstance(result, RunResult):
                        raise TypeError("游戏模块未返回 RunResult")
                    if result.status not in SUCCESS_STATUSES | {"needs_login", "error", "skipped", "unsupported"}:
                        raise ValueError("游戏模块返回了未知状态")
                except AuthRequired as exc:
                    result = RunResult("needs_login", str(exc) or "需要重新登录")
                except Exception as exc:
                    result = RunResult("error", f"{type(exc).__name__}：{exc}")
                finally:
                    if context is not None and context.session is not None:
                        context.session.close()
                result.message = redact(result.message, credential)
                result.details = [redact(item, credential) for item in result.details]
                self._record(module_id, result, day, source, module.platform, credential_revision)
                output[module_id] = result
                self._emit(module_id, result.message, result.status, credential)
        return output

