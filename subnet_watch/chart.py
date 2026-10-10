"""Native candlestick chart; history never participates in price alerts."""
from decimal import Decimal
from datetime import datetime, timezone
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk
from .candles import TIMEFRAMES, HistoryWait
from .core import local_time, price_text
from .providers import ProviderError


class CandleChart(ttk.Frame):
    def __init__(self, master, loader, available, on_error):
        super().__init__(master, padding=(10, 12))
        self.loader, self.available, self.on_error = loader, available, on_error
        self.candles, self.positions = [], []
        self.loading = False
        self.results = queue.Queue()
        self.timer = None
        self.fetched = None
        self.timeframe = tk.StringVar(value="1 hour · 7 days")
        controls = ttk.Frame(self)
        controls.pack(fill="x")
        ttk.Label(controls, text="Candles", font=("Segoe UI", 12, "bold")).pack(side="left")
        self.selector = ttk.Combobox(controls, values=list(TIMEFRAMES), textvariable=self.timeframe,
                                    state="readonly", width=22)
        self.selector.pack(side="left", padx=12)
        self.selector.bind("<<ComboboxSelected>>", lambda _: self.load())
        self.refresh_button = ttk.Button(controls, text="Refresh chart", command=lambda: self.load(force=True))
        self.refresh_button.pack(side="right")
        self.status = ttk.Label(self, text="Historical prices · TAO per alpha", wraplength=730, foreground="#64748b")
        self.status.pack(fill="x", pady=(8, 6))
        self.canvas = tk.Canvas(self, background="white", highlightthickness=0, height=340)
        self.canvas.bind("<Configure>", lambda _: self.draw())
        self.canvas.bind("<Motion>", self.hover)
        self.canvas.bind("<Leave>", lambda _: self.reset_hover())
        self.inspect = ttk.Label(self, text="Hover over a candle for its prices.", wraplength=730)
        self.inspect.pack(side="bottom", fill="x", pady=(10, 4))
        ttk.Label(self, text="Green: close ≥ open   ·   Red: close < open   ·   Times shown in your local time zone",
                  foreground="#64748b", wraplength=730).pack(side="bottom", fill="x", before=self.inspect)
        self.canvas.pack(fill="both", expand=True)
        self.bind("<Destroy>", self.cleanup)

    def load(self, force=False):
        if self.loading:
            return
        if self.timer is not None:
            self.after_cancel(self.timer)
            self.timer = None
        self.force = force
        reason = self.available()
        if reason:
            self.status.configure(text=reason)
            self.draw()
            return
        self.loading = True
        self.status.configure(text="Loading Taostats candle history…")
        self.candles, self.positions, self.fetched = [], [], None
        self.draw()
        self.selector.configure(state="disabled")
        self.refresh_button.configure(state="disabled")
        self.reset_hover()
        chosen = self.timeframe.get()
        def work():
            try:
                self.results.put((self.loader(chosen, force), None))
            except Exception as error:
                self.results.put((None, error if isinstance(error, ProviderError) else
                                  ProviderError("Candle history could not be loaded. Please retry.")))
        threading.Thread(target=work, daemon=True).start()
        self.timer = self.after(50, self.poll)

    def poll(self):
        self.timer = None
        try:
            result, error = self.results.get_nowait()
        except queue.Empty:
            self.timer = self.after(50, self.poll)
            return
        self.loading = False
        self.selector.configure(state="readonly")
        self.refresh_button.configure(state="normal")
        if error:
            self.status.configure(text=str(error))
            if isinstance(error, HistoryWait):
                self.timer = self.after(error.seconds * 1000, lambda: self.load(force=self.force))
            else:
                self.on_error(error)
        elif self.available():
            self.status.configure(text="Connection changed or paused. Reopen Details or refresh the chart when available.")
        else:
            self.candles, self.fetched, cached = result
            stamp = local_time(self.fetched)
            self.status.configure(text=f"Taostats · {len(self.candles)} candles · {'Reused chart' if cached else 'Loaded'}: {stamp}\nRefresh chart for newer history; the newest candle may still be forming.")
        self.draw()

    def cleanup(self, event):
        if event.widget is self and self.timer is not None:
            self.after_cancel(self.timer)
            self.timer = None

    def reset_hover(self):
        self.inspect.configure(text="Hover over a candle for its prices.")
        self.canvas.delete("crosshair")

    def draw(self):
        canvas = self.canvas
        canvas.delete("all")
        self.positions = []
        width, height = canvas.winfo_width(), canvas.winfo_height()
        if width < 150 or height < 100:
            return
        if not self.candles:
            canvas.create_text(width/2, height/2, text="Loading…" if self.loading else "No candle data to display.",
                               fill="#64748b", font=("Segoe UI", 11))
            return
        left, right, top, bottom = 20, width-115, 32, height-40
        low, high = min(c.low for c in self.candles), max(c.high for c in self.candles)
        pad = max((high-low) * Decimal(".07"), high * Decimal(".001"))
        low, high = max(Decimal(0), low-pad), high+pad
        def y(value):
            return bottom - float((value-low)/(high-low)) * (bottom-top)
        canvas.create_text(left, 12, text="TAO per alpha", anchor="w", fill="#64748b", font=("Segoe UI", 9))
        for i in range(5):
            value = low+(high-low)*Decimal(i)/4
            level = y(value)
            canvas.create_line(left, level, right, level, fill="#edf1f6")
            canvas.create_text(right+8, level, text=f"{value:.7g}", anchor="w", fill="#64748b", font=("Segoe UI", 9))
        seconds = TIMEFRAMES[self.timeframe.get()][2]
        start, end = self.candles[0].time-seconds/2, self.candles[-1].time+seconds/2
        step = (right-left) * seconds/(end-start)
        half = max(.6, min(7, step*.32))
        for candle in self.candles:
            x = left+(candle.time-start)/(end-start)*(right-left)
            self.positions.append(x)
            color = "#187454" if candle.close >= candle.open else "#b6444c"
            canvas.create_line(x, y(candle.high), x, y(candle.low), fill=color, tags="wick")
            a, b = sorted((y(candle.open), y(candle.close)))
            if b-a < 1:
                canvas.create_line(x-half, a, x+half, a, fill=color, width=2, tags="body")
            else:
                canvas.create_rectangle(x-half, a, x+half, b, fill=color, outline=color, tags="body")
        for index in sorted({0, len(self.candles)//2, len(self.candles)-1}):
            value = self.candles[index].time
            try:
                label = datetime.fromtimestamp(value, timezone.utc).astimezone().strftime("%b %d\n%H:%M")
            except (ValueError, OverflowError, OSError):
                label = "Time unavailable"
            canvas.create_text(self.positions[index], bottom+22, text=label, fill="#64748b", font=("Segoe UI", 8))

    def hover(self, event):
        if not self.positions:
            return
        index = min(range(len(self.positions)), key=lambda i: abs(self.positions[i]-event.x))
        candle = self.candles[index]
        self.canvas.delete("crosshair")
        self.canvas.create_line(self.positions[index], 30, self.positions[index], self.canvas.winfo_height()-40,
                                fill="#94a3b8", dash=(3, 4), tags="crosshair")
        forming = candle.time + TIMEFRAMES[self.timeframe.get()][2] > time.time()
        self.inspect.configure(text=f"{local_time(candle.time)}{' · Forming' if forming else ''}\n"
                               f"O {price_text(candle.open)}    H {price_text(candle.high)}    "
                               f"L {price_text(candle.low)}    C {price_text(candle.close)}  TAO / alpha")
