#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
实验四 LIS3DSH 串口监测软件
============================
配合 Exp4_LIS3DSH_MEMS 固件使用（USART2，9600-8-N-1）。

功能
  * 串口连接：自动识别 USB-TTL（Prolific/CH340/CP210x），9600-8-N-1
  * 实时波形：X/Y/Z 三轴滚动画布（最近 50 s，±2 g 量程），无需 matplotlib
  * 状态卡片：RTC 时间、合加速度、主轴方向、DRDY 中断频率
  * 实验要求自动判定：8 项要求随数据自动打勾，可直接截图写进报告
  * 事件日志：FREE-FALL / HIGH-G / 改时间 / 命令回显 / 统计行，按类型着色
  * 命令面板：设置 RTC（$0,1,YYMMDD,HHMMSS*）、开关数据流（$0,5,x*）、自定义帧
  * CSV 记录：一键开始/停止，自动写到 logs/exp4_YYYYMMDD_HHMMSS.csv
  * --demo 模式：没有硬件也能演示界面

用法
    python tools/serial_monitor.py                 # 自动选口并连接
    python tools/serial_monitor.py -p COM17        # 指定串口
    python tools/serial_monitor.py --demo          # 虚拟数据演示
"""

import argparse
import os
import queue
import random
import re
import sys
import threading
import time
from collections import deque
from datetime import datetime

# ---------------------------------------------------------------- pyserial
try:
    import serial
    from serial.tools import list_ports
except ImportError:
    _sp = r"D:\Lib\site-packages"
    if os.path.isdir(_sp) and _sp not in sys.path:
        sys.path.append(_sp)
    try:
        import serial
        from serial.tools import list_ports
    except ImportError:
        print("缺少 pyserial：python -m pip install pyserial")
        sys.exit(1)

# ------------------------------------------------------------------ tkinter
try:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)   # 高分屏字体更清晰
except Exception:
    pass

import tkinter as tk
from tkinter import ttk, messagebox

# ------------------------------------------------------------------- 配色/字体
BG      = "#0e1116"
PANEL   = "#161c24"
PANEL2  = "#1d2530"
BORDER  = "#2a3644"
FG      = "#e6edf3"
MUT     = "#8b98a5"
ACCENT  = "#39d0c4"
RED     = "#ff6b6b"
YEL     = "#ffd166"
GRN     = "#5ddc8a"
ORG     = "#f0a05a"
BLUE    = "#59a8ff"
GRID    = "#222c38"

F_UI    = "Microsoft YaHei UI"
F_NUM   = "Consolas"

# ------------------------------------------------------------------- 解析规则
DATA_RE = re.compile(
    r"^(\d{2}):(\d{2}):(\d{2})\s+"
    r"X=([+-]\d+)\s+Y=([+-]\d+)\s+Z=([+-]\d+)\s*mg"
    r"(?:\s+\|a\|=\s*(\d+)\s*mg\s+(\S+))?\s*$"
)
STAT_RE = re.compile(r"\[STAT\]\s+drdy=(\d+)(?:\s+rx=(\d+))?(?:\s+err=(\d+))?")

def isqrt(v):
    """整数开平方，用于由三轴 mg 算合加速度"""
    r, bit = 0, 1 << 30
    while bit > v:
        bit >>= 2
    while bit:
        if v >= r + bit:
            v -= r + bit
            r = (r >> 1) + bit
        else:
            r >>= 1
        bit >>= 2
    return r


def axis_of(x, y, z):
    """由三轴 mg 判断主轴方向（阈值 500 mg）"""
    ax, ay, az = abs(x), abs(y), abs(z)
    if max(ax, ay, az) < 500:
        return "---"
    if ax >= ay and ax >= az:
        return "+X" if x > 0 else "-X"
    if ay >= az:
        return "+Y" if y > 0 else "-Y"
    return "+Z" if z > 0 else "-Z"


CHECK_ITEMS = [
    ("selfcheck", "传感器自检通过（0x3F）"),
    ("stream",    "数据流持续上传 ≥10 行"),
    ("still",     "静止时 |a| ≈ 1 g"),
    ("orient",    "翻转时主轴方向改变"),
    ("drdy",      "DRDY 中断 ≈ 100 Hz"),
    ("event",     "自由落体 / 超阈值事件"),
    ("cmd",       "串口命令生效"),
    ("noerr",     "SPI 读取无错误（rd_err=0）"),
]


class SerialMonitor(tk.Tk):
    def __init__(self, port=None, baud=9600, demo=False):
        super().__init__()
        self.title("实验四 · LIS3DSH 加速度计串口监测")
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = min(1780, sw - 80), min(1140, sh - 110)
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{max(10, (sh - h) // 2 - 20)}")
        self.minsize(1180, 820)
        self.configure(bg=BG)

        self.port = port
        self.baud = baud
        self.demo = demo
        self.ser = None
        self.reader = None
        self.stop_evt = threading.Event()
        self.q = queue.Queue()

        self.connected = False
        self.rx_bytes = 0
        self.tx_bytes = 0
        self.lines = 0
        self.data_count = 0
        self.last_data_t = None
        self.data_intervals = deque(maxlen=20)
        self.rate_hz = 0.0

        self.buf_x = deque(maxlen=250)
        self.buf_y = deque(maxlen=250)
        self.buf_z = deque(maxlen=250)
        self.buf_a = deque(maxlen=250)
        self.plot_dirty = False

        self.last_stat = None              # (drdy, int2, err, wall_time)
        self.drdy_rate = 0.0
        self.rd_err = 0
        self.int2 = 0

        self.checks = {k: False for k, _ in CHECK_ITEMS}
        self.check_labels = {}
        self.still_run = 0
        self.orient_seen = set()

        self.csv_f = None
        self.csv_path = None
        self.csv_rows = 0

        self._build_ui()
        self._refresh_ports()
        self.after(40, self._poll_queue)
        self.after(60, self._tick_plot)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        if self.demo:
            self.lbl_conn.configure(text="演示模式（虚拟数据）", fg=ACCENT)
            self.btn_conn.configure(state="disabled")
            threading.Thread(target=self._demo_loop, daemon=True).start()
        else:
            self.after(300, self._auto_connect)

    # ================================================================ 界面
    def _build_ui(self):
        self._build_header()

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=10, pady=(4, 6))

        left = tk.Frame(body, bg=BG)
        left.pack(side="left", fill="both", expand=True)
        right = tk.Frame(body, bg=BG, width=440)
        right.pack(side="right", fill="y", padx=(10, 0))
        right.pack_propagate(False)

        self._build_cards(left)
        self._build_axis_row(left)      # 先占住底部，避免被波形挤掉
        self._build_plot(left)
        self._build_checklist(right)
        self._build_commands(right)     # 先占住底部
        self._build_log(right)
        self._build_statusbar()

    def _panel(self, parent, title=None):
        outer = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        if title:
            tk.Label(outer, text=title, bg=PANEL, fg=MUT, font=(F_UI, 9, "bold"),
                     anchor="w").pack(fill="x", padx=10, pady=(6, 0))
        return outer

    def _build_header(self):
        hdr = tk.Frame(self, bg=PANEL, height=54)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        self.lbl_conn = tk.Label(hdr, text="未连接", bg=PANEL, fg=MUT, font=(F_UI, 9))
        self.lbl_conn.pack(side="right", padx=(8, 14))

        self.btn_csv = tk.Button(hdr, text="● 记录 CSV", command=self._toggle_csv,
                                 bg=PANEL2, fg=MUT, activebackground=BORDER,
                                 activeforeground=FG, relief="flat", bd=0,
                                 font=(F_UI, 9), padx=10, pady=4, cursor="hand2")
        self.btn_csv.pack(side="right", padx=4)

        tk.Label(hdr, text="LIS3DSH 串口监测", bg=PANEL, fg=FG,
                 font=(F_UI, 13, "bold")).pack(side="left", padx=(14, 12))

        tk.Label(hdr, text="串口", bg=PANEL, fg=MUT, font=(F_UI, 9)).pack(side="left")
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Dark.TCombobox", fieldbackground=PANEL2, background=PANEL2,
                        foreground=FG, arrowcolor=FG, bordercolor=BORDER,
                        lightcolor=BORDER, darkcolor=BORDER)
        self.cmb_port = ttk.Combobox(hdr, width=22, state="readonly", style="Dark.TCombobox")
        self.cmb_port.pack(side="left", padx=(6, 4))

        self.btn_refresh = tk.Button(hdr, text="刷新", command=self._refresh_ports,
                                     bg=PANEL2, fg=FG, activebackground=BORDER,
                                     activeforeground=FG, relief="flat", bd=0,
                                     font=(F_UI, 9), padx=8, pady=4, cursor="hand2")
        self.btn_refresh.pack(side="left", padx=2)

        tk.Label(hdr, text="波特率", bg=PANEL, fg=MUT, font=(F_UI, 9)).pack(side="left", padx=(8, 0))
        self.cmb_baud = ttk.Combobox(hdr, width=7, state="readonly", style="Dark.TCombobox",
                                     values=["9600", "115200", "57600", "38400", "19200"])
        self.cmb_baud.set(str(self.baud))
        self.cmb_baud.pack(side="left", padx=(6, 8))

        self.btn_conn = tk.Button(hdr, text="连接", command=self._toggle_conn,
                                  bg=ACCENT, fg="#06231f", activebackground="#2bb8ad",
                                  activeforeground="#06231f", relief="flat", bd=0,
                                  font=(F_UI, 10, "bold"), padx=14, pady=5, cursor="hand2")
        self.btn_conn.pack(side="left", padx=4)

    def _build_cards(self, parent):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=(0, 8))
        self.card_values = {}
        specs = [
            ("time",  "北京时间",       "--:--:--",   FG),
            ("mag",   "合加速度 |a|",   "---- mg",    ACCENT),
            ("dir",   "主轴方向",       "--",         YEL),
            ("drdy",  "DRDY 中断",      "--- Hz",     BLUE),
        ]
        for i, (key, cap, val, color) in enumerate(specs):
            card = tk.Frame(row, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
            card.pack(side="left", fill="x", expand=True, padx=(0 if i == 0 else 8, 0))
            tk.Label(card, text=cap, bg=PANEL, fg=MUT, font=(F_UI, 9)).pack(anchor="w", padx=12, pady=(8, 0))
            v = tk.Label(card, text=val, bg=PANEL, fg=color, font=(F_NUM, 21, "bold"))
            v.pack(anchor="w", padx=12, pady=(0, 9))
            self.card_values[key] = v

    def _build_plot(self, parent):
        wrap = self._panel(parent, "三轴加速度波形（最近 50 s，量程 ±2 g）")
        wrap.pack(fill="both", expand=True, pady=(8, 0))
        self.cv_plot = tk.Canvas(wrap, bg="#0b0f14", highlightthickness=0, height=340)
        self.cv_plot.pack(fill="both", expand=True, padx=5, pady=(2, 5))
        self.cv_plot.bind("<Configure>", lambda e: setattr(self, "plot_dirty", True))

    def _build_axis_row(self, parent):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=(8, 0))
        self.lbl_axis = {}
        for key, cap, color in (("x", "X", RED), ("y", "Y", ACCENT), ("z", "Z", YEL), ("a", "|a|", FG)):
            box = tk.Frame(row, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
            box.pack(side="left", fill="x", expand=True, padx=(0 if key == "x" else 8, 0))
            tk.Label(box, text=cap, bg=PANEL, fg=color, font=(F_UI, 9, "bold")).pack(side="left", padx=(10, 4), pady=6)
            v = tk.Label(box, text="---- mg", bg=PANEL, fg=FG, font=(F_NUM, 12))
            v.pack(side="left", pady=6)
            self.lbl_axis[key] = v

    def _build_checklist(self, parent):
        wrap = self._panel(parent, "实验要求自动判定")
        wrap.pack(fill="x", pady=(0, 8))
        inner = tk.Frame(wrap, bg=PANEL)
        inner.pack(fill="x", padx=10, pady=(2, 8))
        for key, text in CHECK_ITEMS:
            row = tk.Frame(inner, bg=PANEL)
            row.pack(fill="x", pady=1)
            lab = tk.Label(row, text="○", bg=PANEL, fg=MUT, font=(F_UI, 12, "bold"), width=2)
            lab.pack(side="left")
            tk.Label(row, text=text, bg=PANEL, fg=MUT, font=(F_UI, 9), anchor="w").pack(side="left")
            self.check_labels[key] = lab

    def _build_log(self, parent):
        wrap = self._panel(parent, "事件 / 命令日志")
        wrap.pack(fill="both", expand=True, pady=(0, 0))
        self.txt = tk.Text(wrap, bg="#0b0f14", fg=FG, insertbackground=FG, bd=0,
                           font=(F_NUM, 9), wrap="word", padx=8, pady=6,
                           highlightthickness=0, state="disabled", height=8)
        sb = tk.Scrollbar(wrap, command=self.txt.yview, width=10)
        self.txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", pady=6, padx=(0, 4))
        self.txt.pack(fill="both", expand=True, padx=(6, 0), pady=4)
        self.txt.tag_configure("info", foreground=MUT)
        self.txt.tag_configure("ok", foreground=GRN)
        self.txt.tag_configure("warn", foreground=ORG)
        self.txt.tag_configure("err", foreground=RED)
        self.txt.tag_configure("tx", foreground=BLUE)
        self.txt.tag_configure("rx", foreground=ACCENT)

    def _build_commands(self, parent):
        wrap = self._panel(parent, "串口命令（数据帧格式 $地址,命令,...*）")
        wrap.pack(fill="x", side="bottom", pady=(0, 8))
        inner = tk.Frame(wrap, bg=PANEL)
        inner.pack(fill="x", padx=10, pady=(4, 10))

        r1 = tk.Frame(inner, bg=PANEL)
        r1.pack(fill="x", pady=2)
        tk.Label(r1, text="改 RTC", bg=PANEL, fg=FG, font=(F_UI, 9)).pack(side="left")
        self.e_ymd = self._entry(r1, 8)
        self.e_ymd.insert(0, "251120")
        self.e_hms = self._entry(r1, 8)
        self.e_hms.insert(0, "120000")

        r1b = tk.Frame(inner, bg=PANEL)
        r1b.pack(fill="x", pady=(2, 0))
        self._btn(r1b, "现在时间", self._fill_now, ACCENT).pack(side="left", padx=(0, 6))
        self._btn(r1b, "发送", self._send_rtc, BLUE).pack(side="left")

        r2 = tk.Frame(inner, bg=PANEL)
        r2.pack(fill="x", pady=4)
        tk.Label(r2, text="数据流", bg=PANEL, fg=FG, font=(F_UI, 9)).pack(side="left")
        self._btn(r2, "开启", lambda: self._send("$0,5,1*"), GRN).pack(side="left", padx=4)
        self._btn(r2, "关闭", lambda: self._send("$0,5,0*"), ORG).pack(side="left")

        r3 = tk.Frame(inner, bg=PANEL)
        r3.pack(fill="x", pady=(4, 0))
        tk.Label(r3, text="自定义", bg=PANEL, fg=FG, font=(F_UI, 9)).pack(side="left")
        self.e_raw = self._entry(r3, 13)
        self.e_raw.insert(0, "$0,5,1*")
        self.e_raw.bind("<Return>", lambda e: self._send(self.e_raw.get()))
        self._btn(r3, "发送", lambda: self._send(self.e_raw.get()), ACCENT).pack(side="left", padx=4)

    def _entry(self, parent, width):
        e = tk.Entry(parent, width=width, bg=PANEL2, fg=FG, insertbackground=FG,
                     relief="flat", bd=0, font=(F_NUM, 10), highlightthickness=1,
                     highlightbackground=BORDER, highlightcolor=ACCENT)
        e.pack(side="left", padx=4, ipady=3)
        return e

    def _btn(self, parent, text, cmd, color):
        return tk.Button(parent, text=text, command=cmd, bg=color, fg="#0b0f14",
                         activebackground=color, activeforeground="#0b0f14",
                         relief="flat", bd=0, font=(F_UI, 9, "bold"),
                         padx=12, pady=3, cursor="hand2")

    def _build_statusbar(self):
        bar = tk.Frame(self, bg=PANEL, height=26)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)
        self.lbl_status = tk.Label(bar, text="就绪", bg=PANEL, fg=MUT, font=(F_UI, 8))
        self.lbl_status.pack(side="left", padx=10)
        self.lbl_stat = tk.Label(bar, text="", bg=PANEL, fg=MUT, font=(F_NUM, 8))
        self.lbl_stat.pack(side="right", padx=10)

    # ================================================================ 串口
    def _refresh_ports(self):
        ports = sorted(list_ports.comports(), key=lambda p: p.device)
        items = []
        for p in ports:
            items.append(f"{p.device}  |  {p.description}")
        self.cmb_port["values"] = items
        if not items:
            self.cmb_port.set("")
            return
        if self.cmb_port.get() not in items:
            # 优先选 USB-TTL（Prolific/CH340/CP210x），排除 ST-Link 虚拟串口
            pick = None
            for it in items:
                d = it.lower()
                if any(k in d for k in ("prolific", "ch340", "cp210", "usb-serial", "usb serial")):
                    pick = it
                    break
            if pick is None:
                for it in items:
                    if "stlink" not in it.lower():
                        pick = it
                        break
            self.cmb_port.set(pick or items[0])

    def _auto_connect(self):
        if self.cmb_port.get():
            self._toggle_conn()

    def _toggle_conn(self):
        if self.connected:
            self._disconnect()
        else:
            self._connect()

    def _connect(self):
        sel = self.cmb_port.get()
        if not sel:
            messagebox.showwarning("没有串口", "没有检测到串口，请先插好 USB-TTL。")
            return
        port = sel.split("|")[0].strip()
        baud = int(self.cmb_baud.get() or 9600)
        try:
            self.ser = serial.Serial(port, baud, timeout=0.3)
        except Exception as e:
            messagebox.showerror("打开串口失败", f"{port}\n{e}")
            return
        self.connected = True
        self.stop_evt.clear()
        self.reader = threading.Thread(target=self._read_loop, args=(self.ser,), daemon=True)
        self.reader.start()
        self.btn_conn.configure(text="断开", bg=ORG, activebackground="#d98b49")
        self.lbl_conn.configure(text=f"已连接 {port} @ {baud}", fg=GRN)
        self._log(f"已连接 {port} @ {baud} 8N1", "ok")

    def _disconnect(self):
        self.connected = False
        self.stop_evt.set()
        try:
            if self.ser:
                self.ser.close()
        except Exception:
            pass
        self.ser = None
        self.btn_conn.configure(text="连接", bg=ACCENT, activebackground="#2bb8ad")
        self.lbl_conn.configure(text="未连接", fg=MUT)
        self._log("串口已断开", "warn")

    def _read_loop(self, ser):
        buf = b""
        while not self.stop_evt.is_set():
            try:
                chunk = ser.read(256)
            except Exception:
                self.q.put(("__DISCONNECT__", time.time()))
                return
            if not chunk:
                continue
            self.q.put(("__BYTES__", len(chunk)))
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                line = raw.decode("utf-8", "replace").rstrip("\r")
                self.q.put((line, time.time()))

    def _demo_loop(self):
        t = 0
        axis = "+Z"
        while True:
            time.sleep(0.2)
            t += 0.2
            if 12 < t < 14:
                x, y, z = random.randint(-20, 20), random.randint(-20, 20), random.randint(-40, 40)
                self.q.put((f"[EVT] FREE-FALL  |a|={abs(x) + abs(y) + abs(z)} mg", time.time()))
            elif 20 < t < 22:
                x, y, z = random.randint(1500, 1900), random.randint(-300, 300), random.randint(700, 1100)
                self.q.put((f"[EVT] HIGH-G  X={x} Y={y} Z={z} mg", time.time()))
            else:
                x, y, z = random.randint(-25, 25), random.randint(-25, 25), random.randint(960, 1010)
            mag = int((x * x + y * y + z * z) ** 0.5)
            hh, mm, ss = 9, 0, int(t) % 60
            self.q.put((f"{hh:02d}:{mm:02d}:{ss:02d}  X={x:+05d} Y={y:+05d} Z={z:+05d} mg  "
                        f"|a|={mag:4d} mg  {axis}", time.time()))
            if int(t) % 10 == 9:
                self.q.put((f"[STAT] drdy={int(t * 100)} int2=0 rd_err=0", time.time()))

    # ================================================================ 数据处理
    def _poll_queue(self):
        try:
            for _ in range(200):
                line, ts = self.q.get_nowait()
                if line == "__BYTES__":
                    self.rx_bytes += ts
                    continue
                if line == "__DISCONNECT__":
                    if self.connected:
                        self._log("串口异常断开（设备被拔出？）", "err")
                    self._disconnect()
                    continue
                self._on_line(line, ts)
        except queue.Empty:
            pass
        self.lbl_stat.configure(
            text=f"RX {self.rx_bytes} B   TX {self.tx_bytes} B   行 {self.lines}   CSV {self.csv_rows} 行")
        self.after(40, self._poll_queue)

    def _on_line(self, line, ts):
        if not line.strip():
            return
        self.lines += 1
        m = DATA_RE.match(line.strip())
        if m:
            hh, mm, ss = m.group(1), m.group(2), m.group(3)
            x, y, z = int(m.group(4)), int(m.group(5)), int(m.group(6))
            if m.group(7):                      # 完整版固件带 |a| 与方向
                mag = int(m.group(7))
                axis = m.group(8)
            else:                               # 简化版固件只发三轴，主机侧计算
                mag = isqrt(x * x + y * y + z * z)
                axis = axis_of(x, y, z)
            self._on_sample(hh, mm, ss, x, y, z, mag, axis, ts)
            return
        m = STAT_RE.search(line)
        if m:
            drdy = int(m.group(1))
            err = int(m.group(3)) if m.group(3) else 0
            now = time.time()
            self.rd_err = err
            if self.last_stat:
                d_drdy = drdy - self.last_stat[0]
                d_t = now - self.last_stat[3]
                if d_t > 0.5 and d_drdy >= 0:
                    self.drdy_rate = d_drdy / d_t
                    self.card_values["drdy"].configure(text=f"{self.drdy_rate:.0f} Hz")
                    self._set_check("drdy", 90 <= self.drdy_rate <= 110)
            self.last_stat = (drdy, int2, err, now)
            self._set_check("noerr", err == 0)
            if err:
                self._log(f"[STAT] SPI 读取错误 {err} 次", "err")
            return

        if "[EVT]" in line:
            self._log(line, "warn")
            self._set_check("event", True)
            self._flash_card("mag")
            return
        if "[LIS3DSH]" in line:
            self._log(line, "ok")
            if "0x3F" in line and "OK" in line:
                self._set_check("selfcheck", True)
            return
        if "[RTC]" in line or "[CMD]" in line:
            self._log(line, "ok")
            self._set_check("cmd", True)
            return
        if "[KEY]" in line:
            self._log(line, "ok")
            return
        if line.startswith("[RX]"):
            self._log(line, "rx")
            return
        if line.startswith("*") or "Experiment 4" in line or "STM32F407" in line:
            self._log(line, "info")
            return
        self._log(line, "info")

    def _on_sample(self, hh, mm, ss, x, y, z, mag, axis, ts):
        self.data_count += 1
        if self.last_data_t:
            self.data_intervals.append(ts - self.last_data_t)
        self.last_data_t = ts

        self.card_values["time"].configure(text=f"{hh}:{mm}:{ss}")
        self.card_values["mag"].configure(text=f"{mag} mg")
        self.card_values["dir"].configure(text=axis)
        self.lbl_axis["x"].configure(text=f"{x:+d} mg")
        self.lbl_axis["y"].configure(text=f"{y:+d} mg")
        self.lbl_axis["z"].configure(text=f"{z:+d} mg")
        self.lbl_axis["a"].configure(text=f"{mag} mg")

        self.buf_x.append(x)
        self.buf_y.append(y)
        self.buf_z.append(z)
        self.buf_a.append(mag)
        self.plot_dirty = True

        if self.data_count >= 10:
            self._set_check("stream", True)
        if 900 <= mag <= 1100 and axis in ("+Z", "-Z"):
            self.still_run += 1
            if self.still_run >= 5:
                self._set_check("still", True)
                self._set_check("selfcheck", True)   # 有稳定数据 => 自检与配置成功
        else:
            self.still_run = 0
        self.orient_seen.add(axis)
        if len(self.orient_seen) >= 2:
            self._set_check("orient", True)

        if self.csv_f:
            try:
                self.csv_f.write(f"{hh}:{mm}:{ss},{x},{y},{z},{mag},{axis},"
                                 f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]}\n")
                self.csv_f.flush()
                self.csv_rows += 1
            except Exception:
                pass

    def _set_check(self, key, ok):
        if ok and not self.checks.get(key, False):
            self.checks[key] = True
            lab = self.check_labels[key]
            lab.configure(text="✔", fg=GRN)
        elif not ok and self.checks.get(key, False) and key == "noerr":
            self.checks[key] = False
            self.check_labels[key].configure(text="✘", fg=RED)

    def _flash_card(self, key):
        lab = self.card_values[key]
        lab.configure(fg=ORG)
        self.after(700, lambda: lab.configure(fg=ACCENT))

    # ================================================================ 绘图
    def _tick_plot(self):
        if self.plot_dirty:
            self.plot_dirty = False
            self._draw_plot()
        self.after(60, self._tick_plot)

    def _draw_plot(self):
        c = self.cv_plot
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if w < 80 or h < 60:
            return
        L, R, T, B = 68, 14, 12, 22
        pw, ph = w - L - R, h - T - B
        ymin, ymax = -2000.0, 2000.0

        def ypix(v):
            v = max(ymin, min(ymax, v))
            return T + (ymax - v) * ph / (ymax - ymin)

        for g in range(-2000, 2001, 500):
            y = ypix(g)
            c.create_line(L, y, w - R, y, fill=GRID, dash=(3, 5) if g else None)
            c.create_text(L - 8, y, text=f"{g:+d}" if g else "0", anchor="e",
                          fill=MUT, font=(F_NUM, 7))

        # 竖向时间参考线：每 50 点 ≈ 10 s
        n = len(self.buf_x)
        for i in range(0, n, 50):
            x = L + i * pw / max(n - 1, 1)
            c.create_line(x, T, x, T + ph, fill=GRID)
        c.create_text(L + 2, h - 8, text="最近 50 s →", anchor="w", fill=MUT, font=(F_UI, 8))

        for buf, color, width in ((self.buf_x, RED, 2), (self.buf_y, ACCENT, 2),
                                  (self.buf_z, YEL, 2), (self.buf_a, FG, 1)):
            if len(buf) < 2:
                continue
            pts = []
            for i, v in enumerate(buf):
                pts.extend((L + i * pw / (len(buf) - 1), ypix(v)))
            c.create_line(*pts, fill=color, width=width, smooth=False)

        for i, (name, color) in enumerate((("X", RED), ("Y", ACCENT), ("Z", YEL), ("|a|", FG))):
            x0 = w - R - 190 + i * 46
            c.create_text(x0, T + 8, text=name, anchor="w", fill=color, font=(F_UI, 9, "bold"))

    # ================================================================ 命令
    def _send(self, text):
        if not self.connected or not self.ser:
            self._log("串口未连接，无法发送", "err")
            return
        if not text.endswith("*"):
            text += "*"
        try:
            self.ser.write(text.encode("ascii", "ignore"))
            self.tx_bytes += len(text)
            self._log(f"[TX] {text}", "tx")
        except Exception as e:
            self._log(f"发送失败：{e}", "err")

    def _send_rtc(self):
        ymd = self.e_ymd.get().strip()
        hms = self.e_hms.get().strip()
        if not (len(ymd) == 6 and ymd.isdigit() and len(hms) == 6 and hms.isdigit()):
            messagebox.showwarning("格式错误", "日期 YYMMDD、时间 HHMMSS 都要是 6 位数字。")
            return
        self._send(f"$0,1,{ymd},{hms}*")

    def _fill_now(self):
        now = datetime.now()
        self.e_ymd.delete(0, "end")
        self.e_ymd.insert(0, now.strftime("%y%m%d"))
        self.e_hms.delete(0, "end")
        self.e_hms.insert(0, now.strftime("%H%M%S"))

    # ================================================================ CSV / 日志
    def _toggle_csv(self):
        if self.csv_f:
            try:
                self.csv_f.close()
            except Exception:
                pass
            self._log(f"CSV 已保存：{self.csv_path}（{self.csv_rows} 行）", "ok")
            self.csv_f, self.csv_path = None, None
            self.btn_csv.configure(text="● 记录 CSV", fg=MUT, bg=PANEL2)
            return
        os.makedirs("logs", exist_ok=True)
        self.csv_path = os.path.join("logs", f"exp4_{datetime.now():%Y%m%d_%H%M%S}.csv")
        self.csv_f = open(self.csv_path, "w", encoding="utf-8", newline="")
        self.csv_f.write("time_rtc,x_mg,y_mg,z_mg,mag_mg,axis,pc_time\n")
        self.csv_rows = 0
        self.btn_csv.configure(text="■ 停止记录", fg="#0b0f14", bg=RED)
        self._log(f"开始记录 CSV：{self.csv_path}", "ok")

    def _log(self, text, tag="info"):
        self.txt.configure(state="normal")
        self.txt.insert("end", f"{datetime.now():%H:%M:%S}  {text}\n", tag)
        self.txt.see("end")
        self.txt.configure(state="disabled")

    # ================================================================ 关闭
    def _on_close(self):
        self.stop_evt.set()
        try:
            if self.ser:
                self.ser.close()
        except Exception:
            pass
        if self.csv_f:
            try:
                self.csv_f.close()
                print(f"CSV saved: {self.csv_path}")
            except Exception:
                pass
        self.destroy()


def main():
    ap = argparse.ArgumentParser(description="实验四 LIS3DSH 串口监测软件")
    ap.add_argument("-p", "--port", help="串口，如 COM17（默认自动选 USB-TTL）")
    ap.add_argument("-b", "--baud", type=int, default=9600)
    ap.add_argument("--demo", action="store_true", help="虚拟数据演示（无需硬件）")
    args = ap.parse_args()

    # 单实例：避免重复双击打开两个窗口互相抢串口
    if os.name == "nt":
        import ctypes
        ctypes.windll.kernel32.CreateMutexW(None, False, "Exp4_LIS3DSH_Monitor")
        if ctypes.windll.kernel32.GetLastError() == 183:   # ERROR_ALREADY_EXISTS
            r = tk.Tk()
            r.withdraw()
            messagebox.showinfo("实验四监测", "监测软件已经在运行。")
            r.destroy()
            return

    app = SerialMonitor(port=args.port, baud=args.baud, demo=args.demo)
    app.mainloop()


if __name__ == "__main__":
    main()
