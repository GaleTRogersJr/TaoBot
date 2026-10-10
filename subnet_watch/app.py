"""Native Windows UI. Network work runs off the Tk event loop."""
import queue
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox
from .core import Sample, Alert, evaluate, make_alert, price_text, change_text, local_time
from .providers import DemoProvider, TaostatsProvider, ProviderError
from .storage import Store
from .notifications import Notifications

BG = "#f4f6fa"
INK = "#182536"
MUTED = "#64748b"
BLUE = "#285de1"
GREEN = "#187454"
RED = "#b6444c"


def enable_dpi_awareness():
    # Avoid Windows bitmap scaling and keep the layout/captures in physical pixels.
    import sys
    if sys.platform == "win32":
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            pass


def work_area(root):
    import sys
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        rect = wintypes.RECT()
        if ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(rect), 0):
            return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


class App:
    def __init__(self, root, data_path, notifications=True):
        self.root = root
        self.store = Store(data_path)
        self.samples = {}
        self.alerts = self.store.alerts()
        # A restart is a monitoring gap; preserved armed/done state prevents duplicates.
        for alert in self.alerts:
            alert.gap = True
        self.provider = DemoProvider()
        self.mode = self.store.setting("mode", "demo")
        if self.mode == "taostats":
            self.provider = None  # Credentials intentionally never persist.
        self.interval = self.store.setting("interval", 60)
        self.api_key = ""
        self.events = queue.Queue()
        self.busy = False
        self.generation = 0
        self.next_refresh = 0
        self.error = ""
        self.last_fetch = None
        self.closed = False
        self.age_tick = 0
        self.picked = set()
        self.notify = Notifications() if notifications else None
        self._style()
        self._build()
        self.render()
        root.after(100, self.tick)
        root.protocol("WM_DELETE_WINDOW", self.close)

    def _style(self):
        root = self.root
        root.title("GR Software · Subnet Watch")
        x, y, screen_width, screen_height = work_area(root)
        width, height = min(1280, screen_width-40), min(820, screen_height-60)
        root.geometry(f"{width}x{height}+{x+20}+{y+15}")
        root.minsize(min(1100, screen_width-40), min(700, screen_height-60))
        root.configure(bg=BG)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure(".", font=("Segoe UI", 10))
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background="white")
        style.configure("TLabel", background=BG, foreground=INK, font=("Segoe UI", 10))
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Title.TLabel", font=("Segoe UI", 23, "bold"))
        style.configure("Section.TLabel", font=("Segoe UI", 14, "bold"), background="white")
        style.configure("Card.TLabel", background="white")
        style.configure("TButton", padding=(12, 9), background="#e9eef8", foreground=INK, borderwidth=0)
        style.map("TButton", background=[("active", "#dce5f6")])
        style.configure("Primary.TButton", background=BLUE, foreground="white")
        style.map("Primary.TButton", background=[("active", "#214cb6")], foreground=[("disabled", "#bbc6e0")])
        style.configure("TEntry", padding=8, fieldbackground="white")
        style.configure("TCombobox", padding=7)
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(22, 11), background="#e7edf6", foreground=MUTED)
        style.map("TNotebook.Tab", background=[("selected", "white")], foreground=[("selected", BLUE)])
        style.configure("Treeview", background="white", fieldbackground="white", foreground=INK,
                        rowheight=38, borderwidth=0, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", background="#eef2f8", foreground=MUTED,
                        padding=(8, 6), font=("Segoe UI", 9, "bold"), relief="flat")
        style.map("Treeview", background=[("selected", "#dde8ff")], foreground=[("selected", "#143c85")])

    def _build(self):
        header = ttk.Frame(self.root, padding=(26, 16, 26, 12))
        header.pack(fill="x")
        ttk.Label(header, text="GR SOFTWARE", style="Muted.TLabel").pack(anchor="w")
        row = ttk.Frame(header)
        row.pack(fill="x", pady=(4, 0))
        ttk.Label(row, text="Subnet Watch", style="Title.TLabel").pack(side="left")
        ttk.Button(row, text="Settings", command=self.settings).pack(side="right")
        ttk.Button(row, text="Refresh", command=self.refresh).pack(side="right", padx=8)
        ttk.Button(row, text="Hide to tray", command=self.hide).pack(side="right")
        ttk.Label(header, text="Your subnets. Your prices. Your alerts.", style="Muted.TLabel").pack(anchor="w", pady=(5, 0))
        self.banner = tk.Label(self.root, anchor="w", padx=20, pady=11, font=("Segoe UI", 10),
                               bg="#fff0cc", fg="#7d5316", wraplength=1100)
        self.banner.pack(fill="x", padx=26, pady=(0, 16))
        self.tabs = ttk.Notebook(self.root)
        self.tabs.pack(fill="both", expand=True, padx=26)
        watch_tab, alert_tab, history_tab = (ttk.Frame(self.tabs, padding=(0, 16, 0, 0)) for _ in range(3))
        self.tabs.add(watch_tab, text="Watch")
        self.tabs.add(alert_tab, text="Alerts")
        self.tabs.add(history_tab, text="History")
        watch_tab.columnconfigure(0, weight=0, minsize=330)
        watch_tab.columnconfigure(1, weight=1)
        watch_tab.rowconfigure(0, weight=1)
        picker = ttk.Frame(watch_tab, style="Card.TFrame", padding=16)
        picker.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        picker.rowconfigure(3, weight=1)
        picker.columnconfigure(0, weight=1)
        ttk.Label(picker, text="Add subnets", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(picker, text="Choose as many as you like.", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 12))
        self.search = tk.StringVar()
        entry = ttk.Entry(picker, textvariable=self.search, width=30)
        entry.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        self.search.trace_add("write", lambda *_: self.render_picker())
        self.catalog = self.tree(picker, ("pick", "subnet"), ("", "Search by name or ID"), (32, 250), height=5)
        self.catalog.master.grid(row=3, column=0, sticky="nsew")
        self.catalog.bind("<ButtonRelease-1>", self.pick)
        self.catalog.bind("<space>", self.pick_keyboard)
        self.pick_count = ttk.Label(picker, text="0 selected", style="Card.TLabel")
        self.pick_count.grid(row=4, column=0, sticky="w", pady=(10, 8))
        ttk.Button(picker, text="Add selected to Watch", style="Primary.TButton", command=self.add_selected).grid(row=5, column=0, sticky="ew")
        main = ttk.Frame(watch_tab, style="Card.TFrame", padding=16)
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(2, weight=1)
        title = ttk.Frame(main, style="Card.TFrame")
        title.grid(row=0, column=0, sticky="ew")
        ttk.Label(title, text="Your watch window", style="Section.TLabel").pack(side="left")
        self.watch_count = ttk.Label(title, style="Card.TLabel")
        self.watch_count.pack(side="right")
        ttk.Label(main, text="Prices in TAO per alpha · Change over the last 24 hours", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=(5, 14))
        self.watch = self.tree(main, ("name", "price", "change", "alerts"),
                               ("SUBNET", "TAO / ALPHA", "24H CHANGE", "ALERTS"), (195, 150, 125, 70), height=5)
        self.watch.master.grid(row=2, column=0, sticky="nsew")
        self.watch.bind("<<TreeviewSelect>>", lambda _: self.render_detail())
        self.watch.bind("<Double-1>", lambda _: self.edit_alert())
        self.detail = ttk.Label(main, text="Select a subnet to set an alert.", style="Card.TLabel", wraplength=590)
        self.detail.grid(row=3, column=0, sticky="w", pady=(12, 10))
        actions = ttk.Frame(main, style="Card.TFrame")
        actions.grid(row=4, column=0, sticky="ew")
        ttk.Button(actions, text="+ Price alert", style="Primary.TButton", command=self.edit_alert).pack(side="left")
        ttk.Button(actions, text="Manage alerts", command=lambda: self.tabs.select(1)).pack(side="left", padx=8)
        ttk.Button(actions, text="Remove", command=self.remove_selected).pack(side="right")
        self.watch_empty = ttk.Label(main, style="Card.TLabel", text="Add subnets from the list to start watching.")
        self.watch_empty.grid(row=5, column=0, sticky="w", pady=(8, 0))
        self.alert_tree = self.tree(alert_tab, ("subnet", "condition", "mode", "status"),
                                    ("SUBNET", "ALERT CONDITION", "REPEAT", "STATUS"), (210, 470, 100, 210))
        self.alert_tree.master.pack(fill="both", expand=True)
        self.alert_tree.bind("<Double-1>", lambda _: self.edit_selected_alert())
        self.alert_detail = ttk.Label(alert_tab, style="Muted.TLabel", text="Percentage alerts use the fixed price captured at creation, not the 24-hour change.")
        self.alert_detail.pack(fill="x", pady=12)
        self.alert_tree.bind("<<TreeviewSelect>>", lambda _: self.render_alert_detail())
        row = ttk.Frame(alert_tab)
        row.pack(fill="x")
        ttk.Button(row, text="Edit selected", command=self.edit_selected_alert).pack(side="left")
        ttk.Button(row, text="Pause / resume", command=self.toggle_alert).pack(side="left", padx=8)
        ttk.Button(row, text="Delete selected", command=self.delete_alert).pack(side="left")
        self.history_tree = self.tree(history_tab, ("time", "subnet", "price", "reason"),
                                     ("OBSERVED", "SUBNET", "TAO / ALPHA", "EVENT"), (190, 190, 145, 440))
        self.history_tree.master.pack(fill="both", expand=True)
        self.history_detail = ttk.Label(history_tab, text="Alert events are saved here, including the data source and sample time.",
                                        style="Muted.TLabel", wraplength=1080)
        self.history_detail.pack(fill="x", pady=12)
        self.history_tree.bind("<<TreeviewSelect>>", lambda _: self.render_history_detail())
        self.notice = tk.Label(self.root, text="", bg=BG, fg=BLUE, anchor="w", padx=26, wraplength=1120)
        self.notice.pack(fill="x", pady=(10, 0))
        self.footer = ttk.Label(self.root, style="Muted.TLabel", padding=(26, 10, 26, 16), wraplength=1180)
        # Reserve these before allocating the expandable central area.
        self.footer.pack(side="bottom", fill="x", before=self.tabs)
        self.notice.pack_configure(side="bottom", before=self.tabs)

    def tree(self, parent, columns, headings, widths, height=9):
        frame = ttk.Frame(parent, style="Card.TFrame")
        tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="extended", height=height)
        for col, head, width in zip(columns, headings, widths):
            tree.heading(col, text=head)
            tree.column(col, width=width, minwidth=width if col != "name" else 160, stretch=col in ("subnet", "name", "condition", "reason"), anchor="w")
        ybar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        xbar = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        tree.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        tree.tag_configure("up", foreground=GREEN)
        tree.tag_configure("down", foreground=RED)
        tree.tag_configure("missing", foreground=MUTED)
        return tree

    def mode_samples(self):
        return {key: s for key, s in self.samples.items() if s.source == self.mode}

    def watched(self):
        return {key: item for key, item in self.store.watched().items() if key.startswith(self.mode + ":")}

    def missing_sample(self, key, item):
        return Sample(key, item["netuid"], item["name"], None, None, None, 0, self.mode)

    def render_picker(self):
        if not hasattr(self, "catalog"):
            return
        self.catalog.delete(*self.catalog.get_children())
        query = self.search.get().casefold().strip()
        watched = self.watched()
        for key, s in self.mode_samples().items():
            if query and query not in s.name.casefold() and query not in str(s.netuid):
                continue
            self.catalog.insert("", "end", iid=key, values=("✓" if key in watched else "☑" if key in self.picked else "☐", f"{s.name}   ·   SN {s.netuid}"), tags=("missing",) if key in watched else ())
        self.pick_count.configure(text=f"{len(self.picked)} selected" + (" · No matches" if not self.catalog.get_children() and query else ""))

    def pick(self, event):
        key = self.catalog.identify_row(event.y)
        if key:
            self.toggle_pick(key)

    def pick_keyboard(self, _):
        for key in self.catalog.selection():
            self.toggle_pick(key)
        return "break"

    def toggle_pick(self, key):
        if key not in self.watched():
            if key in self.picked:
                self.picked.remove(key)
            else:
                self.picked.add(key)
        self.render_picker()

    def add_selected(self):
        for key in self.mode_samples():
            if key not in self.picked:
                continue
            if key in self.mode_samples():
                self.store.add_watch(self.samples[key])
        count = len(self.picked)
        self.picked.clear()
        self.notice.configure(text=f"Added {count} subnet(s) to Watch." if count else "Select subnets in the list first.")
        self.render()

    def remove_selected(self):
        selected = self.watch.selection()
        if selected and messagebox.askyesno("Remove from Watch", "Remove selected subnets and their alerts? Saved alert history will remain.", parent=self.root):
            for key in selected:
                self.store.remove_watch(key)
            self.alerts = self.store.alerts()
            self.render()

    def render(self):
        self.render_picker()
        self.render_watch()
        selected_alerts = self.alert_tree.selection()
        self.alert_tree.delete(*self.alert_tree.get_children())
        for a in self.alerts:
            if a.key.startswith(self.mode + ":"):
                self.alert_tree.insert("", "end", iid=a.id, values=(a.name, a.description, "Repeating" if a.repeat else "One-shot", a.status))
        self.alert_tree.selection_set([i for i in selected_alerts if self.alert_tree.exists(i)])
        self.render_alert_detail()
        self.history_tree.delete(*self.history_tree.get_children())
        for e in self.store.history():
            if e["source"] == self.mode:
                self.history_tree.insert("", "end", iid=e["id"], values=(local_time(e["observed_time"]), e["name"], e["price"], e["reason"]))
        self.render_status()

    def render_watch(self):
        now = time.time()
        watched = self.watched()
        for key in self.watch.get_children():
            if key not in watched:
                self.watch.delete(key)
        for key, item in watched.items():
            s = self.mode_samples().get(key) or self.missing_sample(key, item)
            tag = "missing" if not s.fresh(now) else "up" if s.change_24h is not None and s.change_24h >= 0 else "down" if s.change_24h is not None else "missing"
            price = price_text(s.price) + (" · stale" if s.price is not None and not s.fresh(now) else "")
            count = sum(a.key == key and a.enabled and not a.done for a in self.alerts)
            values = (f"{s.name} · SN {s.netuid}", price, change_text(s.change_24h), count)
            if self.watch.exists(key):
                self.watch.item(key, values=values, tags=(tag,))
            else:
                self.watch.insert("", "end", iid=key, values=values, tags=(tag,))
        self.watch_count.configure(text=f"{len(watched)} subnets")
        self.watch_empty.configure(text="Add subnets from the list to start watching." if not watched else "")
        if watched:
            self.watch_empty.grid_remove()
        else:
            self.watch_empty.grid()
        self.render_detail()

    def render_detail(self):
        keys = self.watch.selection()
        if not keys:
            self.detail.configure(text="Select a subnet to set an alert.")
            return
        s = self.mode_samples().get(keys[0])
        if s:
            state = "Fresh sample" if s.fresh(time.time()) else "Stale / invalid sample · alerts paused for this subnet"
            self.detail.configure(text=f"{state} · Sample: {local_time(s.source_time)}")
        else:
            self.detail.configure(text="Current price unavailable. Waiting for a valid provider sample.")

    def render_status(self):
        if self.mode == "demo":
            text = "DEMO DATA · Synthetic subnet names and prices. These are not real market values."
            color, ink = "#fff0cc", "#7d5316"
        else:
            text = "TAOSTATS · Connecting…" if self.busy else "TAOSTATS · Read-only price monitoring"
            color, ink = "#e6efff", "#235090"
        if self.error:
            text += "  |  " + self.error + "  Alerts wait for fresh data."
            color, ink = "#ffebec", RED
        elif self.busy:
            text += "  |  Refreshing…"
        elif self.samples and any(not s.fresh(time.time()) for s in self.mode_samples().values()):
            text += "  |  Some data is stale or invalid; those alerts are paused."
        elif not self.mode_samples():
            text += "  |  No price data loaded."
        warning = getattr(self.provider, "warning", "")
        if warning and not self.error:
            text += "  |  " + warning
        self.banner.configure(text=text, bg=color, fg=ink)
        self.footer.configure(text=f"Last fetch: {local_time(self.last_fetch)}   ·   Refresh: {self.interval}s   ·   Monitoring runs while this program is open and your PC is awake.", wraplength=max(700, self.root.winfo_width()-70))

    def refresh(self):
        if self.busy:
            return
        if self.provider is None:
            self.error = "API key needed. Open Settings to connect."
            self.render_status()
            return
        self.busy = True
        self.render_status()
        generation, provider = self.generation, self.provider

        def work():
            try:
                result = provider.fetch()
                self.events.put((generation, result, None))
            except Exception as exc:
                # Known errors carry safe explanations; never render secret-bearing traces.
                self.events.put((generation, None, str(exc) if isinstance(exc, ProviderError) else "Provider returned unexpected data. Refresh could not complete."))
        threading.Thread(target=work, daemon=True).start()

    def apply_samples(self, samples):
        incoming = {s.key: s for s in samples}
        # Reject regressed/duplicate timestamps for display as well as evaluation.
        for key, s in list(incoming.items()):
            old = self.samples.get(key)
            if old and old.source_time is not None and s.source_time is not None and s.source_time <= old.source_time:
                incoming[key] = old
        self.samples = incoming
        now, events = time.time(), []
        for a in self.alerts:
            s = self.samples.get(a.key)
            if s is None:
                a.gap = True
            else:
                event = evaluate(a, s, now)
                if event:
                    events.append(event)
        self.store.persist_evaluation(self.alerts, events)
        for e in events:
            prefix = "DEMO · " if e["source"] == "demo" else ""
            body = f"{prefix}{e['name']}: {e['price']} TAO / alpha. {e['reason']}."
            self.notice.configure(text=body)
            if self.notify:
                self.notify.show("GR Subnet Watch · Price alert", body)
        self.error = ""
        self.last_fetch = now
        self.render()

    def tick(self):
        if self.closed:
            return
        try:
            while True:
                generation, samples, error = self.events.get_nowait()
                if generation != self.generation:
                    continue
                self.busy = False
                self.next_refresh = time.time() + self.interval
                if error:
                    self.error = error
                    for a in self.alerts:
                        a.gap = True
                    self.store.persist_evaluation(self.alerts, [])
                    self.render_status()
                else:
                    self.apply_samples(samples)
        except queue.Empty:
            pass
        if self.notify:
            try:
                while True:
                    self.notify.actions.get_nowait()
                    self.root.deiconify()
                    self.root.lift()
            except queue.Empty:
                pass
        if not self.busy and time.time() >= self.next_refresh:
            self.next_refresh = time.time() + self.interval
            self.refresh()
        self.render_status()
        self.render_detail()
        if int(time.time()) != self.age_tick:
            self.age_tick = int(time.time())
            self.render_watch()
        self.root.after(250, self.tick)

    def selected_alert(self):
        ids = self.alert_tree.selection()
        return next((a for a in self.alerts if ids and a.id == ids[0]), None)

    def render_alert_detail(self):
        a = self.selected_alert()
        if not a:
            self.alert_detail.configure(text="Select an alert to edit, pause or delete. Percentage references stay fixed until edited.")
        else:
            baseline = f"Reference: {a.baseline} TAO / alpha · Captured {local_time(a.baseline_time)} · " if a.kind == "percent" else ""
            self.alert_detail.configure(text=baseline + (f"Rearms when condition clears · Cooldown {a.cooldown}s" if a.repeat else "Triggers once, then remains in the list as completed."))

    def render_history_detail(self):
        ids = self.history_tree.selection()
        event = next((e for e in self.store.history() if ids and e["id"] == ids[0]), None)
        if event:
            self.history_detail.configure(text=f"{event['condition']} · Source: {event['source']} · Sample: {local_time(event['source_time'])}\n{event['reason']} · Observed: {local_time(event['observed_time'])}")

    def toggle_alert(self):
        a = self.selected_alert()
        if not a:
            return
        if a.done:
            self.notice.configure(text="This one-shot alert is complete. Edit it to create a fresh alert.")
            return
        a.enabled = not a.enabled
        a.gap = True
        self.store.save_alert(a)
        self.render()

    def delete_alert(self):
        ids = self.alert_tree.selection()
        if ids and messagebox.askyesno("Delete alerts", "Delete selected alerts? Saved history remains.", parent=self.root):
            for alert_id in ids:
                self.store.delete_alert(alert_id)
            self.alerts = self.store.alerts()
            self.render()

    def edit_selected_alert(self):
        a = self.selected_alert()
        if a:
            self.edit_alert(existing=a)

    def edit_alert(self, existing=None):
        keys = self.watch.selection()
        key = existing.key if existing else keys[0] if keys else None
        if not key:
            self.notice.configure(text="Select a subnet in Watch first, then choose Price alert.")
            return
        item = self.store.watched().get(key)
        if not item:
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("Edit price alert" if existing else "New price alert")
        dialog.geometry("560x700")
        dialog.resizable(False, False)
        dialog.configure(bg=BG)
        dialog.transient(self.root)
        self.position_dialog(dialog, 560, 700)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=26)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=item["name"], font=("Segoe UI", 17, "bold")).pack(anchor="w")
        s = self.mode_samples().get(key) or self.missing_sample(key, item)
        ttk.Label(frame, text=f"Current: {price_text(s.price)} TAO / alpha", style="Muted.TLabel").pack(anchor="w", pady=(5, 18))
        kind = tk.StringVar(value=existing.kind if existing else "target")
        row = ttk.Frame(frame)
        row.pack(fill="x")
        ttk.Radiobutton(row, text="Specific price", variable=kind, value="target").pack(side="left")
        ttk.Radiobutton(row, text="Percentage change", variable=kind, value="percent").pack(side="left", padx=22)
        ttk.Label(frame, text="Alert me when the price is").pack(anchor="w", pady=(18, 7))
        direction = tk.StringVar()
        combo = ttk.Combobox(frame, textvariable=direction, state="readonly")
        combo.pack(fill="x")
        units = ttk.Label(frame)
        units.pack(anchor="w", pady=(15, 7))
        amount = tk.StringVar(value=existing.amount if existing else "")
        amount_entry = ttk.Entry(frame, textvariable=amount)
        amount_entry.pack(fill="x")
        reference = ttk.Label(frame, style="Muted.TLabel", wraplength=480)
        reference.pack(anchor="w", pady=12)
        repeat = tk.BooleanVar(value=existing.repeat if existing else False)
        ttk.Checkbutton(frame, text="Repeat after the condition clears", variable=repeat).pack(anchor="w", pady=5)
        ttk.Label(frame, text="Repeat cooldown (seconds)").pack(anchor="w", pady=(12, 7))
        cooldown = tk.StringVar(value=str(existing.cooldown if existing else 300))
        dialog._variables = [kind, direction, amount, repeat, cooldown]
        ttk.Entry(frame, textvariable=cooldown).pack(fill="x")
        feedback = ttk.Label(frame, foreground=RED, wraplength=480)
        feedback.pack(anchor="w", pady=12)

        def update(*_):
            values = ("At or above", "At or below") if kind.get() == "target" else ("Rises by", "Falls by", "Either direction")
            combo.configure(values=values)
            combo.current(2 if existing and existing.direction == "either" and kind.get() == "percent" else 1 if existing and existing.direction == "down" else 0)
            units.configure(text="Target price · TAO per alpha" if kind.get() == "target" else "Change · percent (%)")
            reference.configure(text="Percentage reference will use the latest fresh price when saved. It stays fixed until edited. This is separate from the displayed 24h change." if kind.get() == "percent" else "Example: 0.3 means 0.3 TAO per alpha. Equality counts as reaching the target.")
        kind.trace_add("write", update)
        update()

        def save():
            try:
                latest = self.mode_samples().get(key) or self.missing_sample(key, item)
                a = make_alert(latest, kind.get(), ("up", "down", "either")[combo.current()], amount.get(), repeat.get(), int(cooldown.get()), time.time())
                if existing:
                    a.id = existing.id
                self.store.save_alert(a)
                self.alerts = self.store.alerts()
                self.notice.configure(text=f"Alert saved for {a.name}. " + (f"Reference: {a.baseline} TAO / alpha, captured {local_time(a.baseline_time)}." if a.kind == "percent" else a.description))
                dialog.destroy()
                self.render()
            except (ValueError, TypeError) as exc:
                feedback.configure(text=str(exc) if not isinstance(exc, ValueError) or "invalid literal" not in str(exc) else "Enter a whole number of seconds for cooldown.")
        buttons = ttk.Frame(frame)
        buttons.pack(side="bottom", fill="x", before=frame.winfo_children()[0])
        ttk.Button(buttons, text="Save alert", style="Primary.TButton", command=save).pack(side="right")
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="right", padx=8)
        amount_entry.focus_set()
        return dialog

    def settings(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Data & settings")
        dialog.geometry("580x760")
        dialog.resizable(False, False)
        dialog.configure(bg=BG)
        dialog.transient(self.root)
        self.position_dialog(dialog, 580, 760)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=26)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Data & settings", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Choose a data source", style="Muted.TLabel").pack(anchor="w", pady=(15, 8))
        mode = tk.StringVar(value="Demo data" if self.mode == "demo" else "Taostats API")
        ttk.Combobox(frame, values=("Demo data", "Taostats API"), state="readonly", textvariable=mode).pack(fill="x")
        ttk.Label(frame, text="Taostats API key (kept only for this session)").pack(anchor="w", pady=(18, 7))
        key = tk.StringVar(value=self.api_key)
        ttk.Entry(frame, textvariable=key, show="•").pack(fill="x")
        ttk.Label(frame, text="Refresh interval · seconds (30–3600)").pack(anchor="w", pady=(18, 7))
        interval = tk.StringVar(value=str(self.interval))
        dialog._variables = [mode, key, interval]
        ttk.Entry(frame, textvariable=interval).pack(fill="x")
        ttk.Label(frame, text="API use must fit your Taostats plan. Each refresh pages through all current pools; subnet names refresh hourly. Live and demo watchlists and alerts are separate.",
                  style="Muted.TLabel", wraplength=495).pack(anchor="w", pady=16)
        native = bool(self.notify and self.notify.available)
        ttk.Label(frame, text="Windows tray notifications available." if native else "Windows notifications unavailable; alerts appear in-app and in History.",
                  style="Muted.TLabel", wraplength=495).pack(anchor="w")
        ttk.Button(frame, text="Test notification", command=self.test_notification).pack(anchor="w", pady=12)
        ttk.Label(frame, text="Monitoring runs while the program is open or hidden to tray and your PC is awake. Closing it stops monitoring. Windows may suppress banners depending on your notification settings.",
                  style="Muted.TLabel", wraplength=495).pack(anchor="w")
        feedback = ttk.Label(frame, foreground=RED, wraplength=495)
        feedback.pack(anchor="w", pady=10)

        def save():
            try:
                seconds = int(interval.get())
                if not 30 <= seconds <= 3600:
                    raise ValueError("Refresh interval must be between 30 and 3600 seconds.")
                chosen = "demo" if mode.get() == "Demo data" else "taostats"
                provider = DemoProvider() if chosen == "demo" else TaostatsProvider(key.get())
                self.generation += 1
                self.busy = False
                self.mode, self.provider, self.interval = chosen, provider, seconds
                self.api_key = key.get().strip() if chosen == "taostats" else ""
                self.samples = {}
                self.picked.clear()
                self.last_fetch, self.error = None, ""
                self.store.set_setting("mode", chosen)
                self.store.set_setting("interval", seconds)
                for a in self.alerts:
                    a.gap = True
                self.next_refresh = 0
                dialog.destroy()
                self.render()
            except (ValueError, ProviderError) as exc:
                feedback.configure(text=str(exc) if "invalid literal" not in str(exc) else "Enter a whole number of seconds.")
        row = ttk.Frame(frame)
        row.pack(side="bottom", fill="x", before=frame.winfo_children()[0])
        ttk.Button(row, text="Save & connect", style="Primary.TButton", command=save).pack(side="right")
        ttk.Button(row, text="Cancel", command=dialog.destroy).pack(side="right", padx=8)
        return dialog

    def test_notification(self):
        sent = bool(self.notify and self.notify.show("GR Subnet Watch · Test", "Test notification. Real alert events also remain in History."))
        self.notice.configure(text="Test sent to Windows. Check your notification settings if no banner appears." if sent else "Test notification: in-app fallback is working. Windows delivery is unavailable.")

    def position_dialog(self, dialog, width, height):
        x, y, sw, sh = work_area(self.root)
        height = min(height, sh-55)
        dialog.geometry(f"{width}x{height}+{x+max(10, (sw-width)//2)}+{y+max(10, (sh-height-35)//2)}")

    def hide(self):
        if self.notify and self.notify.available:
            self.root.withdraw()
            self.notify.show("GR Subnet Watch", "Monitoring continues. Click the tray icon to reopen the watch window.")
        else:
            self.root.iconify()
            self.notice.configure(text="Tray unavailable. Minimized to the taskbar; monitoring continues.")

    def close(self):
        self.closed = True
        if self.notify:
            self.notify.close()
        self.store.close()
        self.root.destroy()


def run(data_path=None, verify_output=None):
    enable_dpi_awareness()
    root = tk.Tk()
    app = App(root, data_path or Path(__file__).resolve().parent.parent / "data" / "watch.sqlite3")
    if verify_output:
        def finish_verification():
            import json
            report = {"title": root.title(), "viewport": [root.winfo_width(), root.winfo_height()],
                      "demo_samples_loaded": len(app.samples), "native_tray": bool(app.notify and app.notify.available)}
            Path(verify_output).write_text(json.dumps(report, indent=2))
            app.close()
        root.after(1500, finish_verification)
    root.mainloop()
