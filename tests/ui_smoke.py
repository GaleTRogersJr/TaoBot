"""Exercise actual Tk forms and capture only this app's windows for review.

Pillow is optional QA tooling; the app itself uses only Python's stdlib.
"""
import json
from pathlib import Path
import sys
import time
import tkinter as tk
from tkinter import ttk
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from subnet_watch.app import App, enable_dpi_awareness
from subnet_watch.core import make_alert
from subnet_watch.providers import DemoProvider
from PIL import Image, ImageGrab
import ctypes
from ctypes import wintypes as w


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "qa"
OUT.mkdir(exist_ok=True)
DB = OUT / "smoke.sqlite3"
if DB.exists():
    DB.unlink()


def descendants(widget):
    return [child for w in widget.winfo_children() for child in [w, *descendants(w)]]


def capture(widget, name):
    widget.update()
    widget.lift()
    widget.focus_force()
    widget.update()
    time.sleep(.2)
    # Capture the application's own HWND. Never screenshot other apps/the desktop.
    user, gdi = ctypes.windll.user32, ctypes.windll.gdi32
    user.GetAncestor.argtypes = [w.HWND, w.UINT]
    user.GetAncestor.restype = w.HWND
    user.GetForegroundWindow.restype = w.HWND
    own_hwnd = user.GetAncestor(widget.winfo_id(), 2)
    if user.GetForegroundWindow() == own_hwnd:
        x, y = widget.winfo_rootx(), widget.winfo_rooty()
        ImageGrab.grab(bbox=(x, y, x+widget.winfo_width(), y+widget.winfo_height())).save(OUT/name)
        return
    user.GetDC.argtypes = [w.HWND]
    user.GetDC.restype = w.HDC
    user.ReleaseDC.argtypes = [w.HWND, w.HDC]
    user.PrintWindow.argtypes = [w.HWND, w.HDC, w.UINT]
    gdi.CreateCompatibleDC.argtypes = [w.HDC]
    gdi.CreateCompatibleDC.restype = w.HDC
    gdi.CreateCompatibleBitmap.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int]
    gdi.CreateCompatibleBitmap.restype = w.HBITMAP
    gdi.SelectObject.argtypes = [w.HDC, w.HGDIOBJ]
    gdi.SelectObject.restype = w.HGDIOBJ
    gdi.DeleteObject.argtypes = [w.HGDIOBJ]
    gdi.DeleteDC.argtypes = [w.HDC]
    gdi.GetDIBits.argtypes = [w.HDC, w.HBITMAP, w.UINT, w.UINT, w.LPVOID, w.LPVOID, w.UINT]
    user.GetClientRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
    user.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
    rect = w.RECT()
    user.GetWindowRect(own_hwnd, ctypes.byref(rect))
    hwnd, width, height = own_hwnd, rect.right - rect.left, rect.bottom - rect.top
    dc = user.GetDC(hwnd)
    mem = gdi.CreateCompatibleDC(dc)
    bitmap = gdi.CreateCompatibleBitmap(dc, width, height)
    old = gdi.SelectObject(mem, bitmap)
    try:
        assert user.PrintWindow(hwnd, mem, 2), "Could not render this app window."
        gdi.SelectObject(mem, old)
        info = ctypes.create_string_buffer(40)
        import struct
        info.raw = struct.pack("<IiiHHIIiiII", 40, width, -height, 1, 32, 0, width*height*4, 0, 0, 0, 0)
        pixels = ctypes.create_string_buffer(width*height*4)
        assert gdi.GetDIBits(mem, bitmap, 0, height, pixels, info, 0)
        Image.frombytes("RGB", (width, height), pixels.raw, "raw", "BGRX").save(OUT/name)
    finally:
        gdi.DeleteObject(bitmap)
        gdi.DeleteDC(mem)
        user.ReleaseDC(hwnd, dc)


enable_dpi_awareness()
root = tk.Tk()
app = App(root, DB, notifications=True)
app.next_refresh = float("inf")
app.apply_samples(DemoProvider().fetch())
app.picked.update(["demo:1", "demo:2", "demo:3"])
app.add_selected()
app.watch.selection_set("demo:1")
root.update()
dialog = app.edit_alert()
entries = [w for w in descendants(dialog) if type(w) is ttk.Entry]
entries[0].insert(0, "0.3")
capture(dialog, "alert-editor.png")
save = next(w for w in descendants(dialog) if isinstance(w, ttk.Button) and w.cget("text") == "Save alert")
save.invoke()
assert len(app.alerts) == 1
assert app.alerts[0].direction == "up"
dialog = app.edit_alert()
radio = next(w for w in descendants(dialog) if isinstance(w, ttk.Radiobutton) and w.cget("text") == "Percentage change")
radio.invoke()
entries = [w for w in descendants(dialog) if type(w) is ttk.Entry]
entries[0].insert(0, "10")
combo = next(w for w in descendants(dialog) if isinstance(w, ttk.Combobox))
assert tuple(combo.cget("values")) == ("Rises by", "Falls by", "Either direction")
combo.current(2)
capture(dialog, "percentage-either-editor.png")
save = next(w for w in descendants(dialog) if isinstance(w, ttk.Button) and w.cget("text") == "Save alert")
save.invoke()
assert len(app.alerts) == 2
assert app.alerts[1].baseline is not None
assert app.alerts[1].direction == "either"
reopened = app.edit_alert(existing=app.alerts[1])
combo = next(w for w in descendants(reopened) if isinstance(w, ttk.Combobox))
assert combo.current() == 2
assert combo.get() == "Either direction"
reopened.destroy()
capture(root, "watch-window.png")
app.tabs.select(1)
capture(root, "alerts-window.png")
app.alert_tree.selection_set(app.alerts[1].id)
app.toggle_alert()
assert not app.alerts[1].enabled
app.toggle_alert()
assert app.alerts[1].enabled
app.tabs.select(0)
settings = app.settings()
capture(settings, "settings-window.png")
overflow = []
for widget_item in descendants(settings):
    if widget_item.winfo_ismapped() and widget_item.winfo_rooty() + widget_item.winfo_height() > settings.winfo_rooty() + settings.winfo_height():
        overflow.append(str(widget_item))
assert not overflow, f"Settings overflow: {overflow}"
settings.destroy()
for i in range(1, 251):
    s = app.samples["demo:1"]
    from dataclasses import replace
    item = replace(s, key=f"demo:{i}", netuid=i, name=f"Demo · Subnet {i}")
    app.store.add_watch(item)
    app.samples[item.key] = item
app.render()
root.geometry("1100x700")
root.update()
assert len(app.watch.get_children()) == 250
assert app.watch.yview()[1] < 1
assert app.watch.yview()[1] > 0
app.watch.yview_moveto(.5)
root.update()
scroll_before = app.watch.yview()[0]
app.render_watch()
root.update()
assert app.watch.yview()[0] == scroll_before, "Refreshing watch values changed scroll position."
app.watch.yview_moveto(0)
capture(root, "large-watch-small-window.png")
report = {"watch_rows": len(app.watch.get_children()), "viewport": [root.winfo_width(), root.winfo_height()],
          "watch_scroll_fraction": app.watch.yview(), "alerts_created_through_form": 2,
          "percentage_reference_saved": True, "either_direction_saved_and_reopened": True, "pause_resume": True,
          "windows_tray_registered": bool(app.notify and app.notify.available),
          "native_banner_delivery": "Not visually verified; OS may suppress banners",
          "screenshots": ["watch-window.png", "alerts-window.png", "alert-editor.png", "percentage-either-editor.png", "settings-window.png", "large-watch-small-window.png"]}
app.close()
(OUT/"ui-smoke-report.json").write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
