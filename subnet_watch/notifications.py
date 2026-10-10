"""Optional native Windows tray icon and balloon notifications (no dependency)."""
import ctypes
from ctypes import wintypes as w
import queue
import sys
import threading


class Notifications:
    def __init__(self):
        self.actions = queue.Queue()
        self.ready = threading.Event()
        self.available = False
        self.hwnd = None
        if sys.platform == "win32":
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()
            self.ready.wait(2)

    def _run(self):
        try:
            user = ctypes.WinDLL("user32", use_last_error=True)
            shell = ctypes.WinDLL("shell32", use_last_error=True)
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            callback = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM)

            class WNDCLASS(ctypes.Structure):
                _fields_ = [("style", w.UINT), ("lpfnWndProc", callback), ("cbClsExtra", ctypes.c_int),
                            ("cbWndExtra", ctypes.c_int), ("hInstance", w.HINSTANCE), ("hIcon", w.HICON),
                            ("hCursor", w.HANDLE), ("hbrBackground", w.HANDLE), ("lpszMenuName", w.LPCWSTR),
                            ("lpszClassName", w.LPCWSTR)]

            class GUID(ctypes.Structure):
                _fields_ = [("Data1", w.DWORD), ("Data2", w.WORD), ("Data3", w.WORD), ("Data4", ctypes.c_ubyte * 8)]

            class NID(ctypes.Structure):
                _fields_ = [("cbSize", w.DWORD), ("hWnd", w.HWND), ("uID", w.UINT), ("uFlags", w.UINT),
                            ("uCallbackMessage", w.UINT), ("hIcon", w.HICON), ("szTip", w.WCHAR * 128),
                            ("dwState", w.DWORD), ("dwStateMask", w.DWORD), ("szInfo", w.WCHAR * 256),
                            ("uTimeoutOrVersion", w.UINT), ("szInfoTitle", w.WCHAR * 64), ("dwInfoFlags", w.DWORD),
                            ("guidItem", GUID), ("hBalloonIcon", w.HICON)]

            user.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
            user.DefWindowProcW.restype = ctypes.c_ssize_t
            user.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, ctypes.c_int, ctypes.c_int,
                                            ctypes.c_int, ctypes.c_int, w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID]
            user.CreateWindowExW.restype = w.HWND
            user.LoadIconW.argtypes = [w.HINSTANCE, ctypes.c_void_p]
            user.LoadIconW.restype = w.HICON
            kernel.GetModuleHandleW.restype = w.HMODULE
            shell.Shell_NotifyIconW.argtypes = [w.DWORD, ctypes.POINTER(NID)]
            user.DestroyWindow.argtypes = [w.HWND]
            user.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]

            @callback
            def proc(hwnd, msg, wp, lp):
                if msg == 0x8001 and lp in (0x202, 0x203, 0x205, 0x405):
                    self.actions.put("show")
                    return 0
                if msg == 0x10:
                    shell.Shell_NotifyIconW(2, ctypes.byref(self.nid))
                    user.DestroyWindow(hwnd)
                    return 0
                if msg == 2:
                    user.PostQuitMessage(0)
                    return 0
                return user.DefWindowProcW(hwnd, msg, wp, lp)

            self.proc = proc
            name = "GRSubnetWatchTray" + str(id(self))
            wc = WNDCLASS()
            wc.lpfnWndProc, wc.hInstance, wc.lpszClassName = proc, kernel.GetModuleHandleW(None), name
            user.RegisterClassW(ctypes.byref(wc))
            self.hwnd = user.CreateWindowExW(0, name, "GR Subnet Watch", 0, 0, 0, 0, 0, None, None, wc.hInstance, None)
            self.nid = NID()
            self.nid.cbSize = ctypes.sizeof(NID)
            self.nid.hWnd, self.nid.uID, self.nid.uFlags = self.hwnd, 1, 1 | 2 | 4
            self.nid.uCallbackMessage = 0x8001
            self.nid.hIcon = user.LoadIconW(None, ctypes.c_void_p(32516))
            self.nid.szTip = "GR Subnet Watch · Click to restore"
            self.shell, self.user = shell, user
            self.available = bool(self.hwnd and shell.Shell_NotifyIconW(0, ctypes.byref(self.nid)))
            self.ready.set()
            msg = w.MSG()
            while user.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user.TranslateMessage(ctypes.byref(msg))
                user.DispatchMessageW(ctypes.byref(msg))
        except Exception:
            self.available = False
            self.ready.set()

    def show(self, title, body):
        if not self.available:
            return False
        self.nid.uFlags = 0x10
        self.nid.szInfoTitle, self.nid.szInfo = title[:63], body[:255]
        self.nid.dwInfoFlags = 1
        return bool(self.shell.Shell_NotifyIconW(1, ctypes.byref(self.nid)))

    def close(self):
        if self.hwnd:
            self.user.PostMessageW(self.hwnd, 0x10, 0, 0)
