"""后台失败时使用Windows通知区提示，不阻塞用户或启动终端窗口。"""
def notify(title, message):
    import os
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes
    import time
    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]
    class NOTIFYICONDATA(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT), ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON), ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD), ("szInfo", wintypes.WCHAR * 256), ("uTimeoutOrVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64), ("dwInfoFlags", wintypes.DWORD), ("guidItem", GUID), ("hBalloonIcon", wintypes.HICON)]
    try:
        user32, shell32 = ctypes.windll.user32, ctypes.windll.shell32
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
        window = user32.CreateWindowExW(0, "STATIC", "CommunityCheckinNotice", 0, 0, 0, 0, 0, None, None, None, None)
        user32.LoadIconW.restype = wintypes.HICON
        icon = user32.LoadIconW(None, ctypes.c_void_p(32516))
        item = NOTIFYICONDATA()
        item.cbSize = ctypes.sizeof(item)
        item.hWnd, item.uID, item.uFlags, item.hIcon = window, 1, 0x2 | 0x4 | 0x10, icon
        item.szTip, item.szInfoTitle, item.szInfo, item.dwInfoFlags = "每日签到", title[:63], message[:255], 1
        shell32.Shell_NotifyIconW(0, ctypes.byref(item))
        end = time.monotonic() + 6
        msg = wintypes.MSG()
        while time.monotonic() < end:
            while user32.PeekMessageW(ctypes.byref(msg), window, 0, 0, 1):
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            time.sleep(0.1)
        shell32.Shell_NotifyIconW(2, ctypes.byref(item))
        user32.DestroyWindow(window)
    except Exception:
        pass
