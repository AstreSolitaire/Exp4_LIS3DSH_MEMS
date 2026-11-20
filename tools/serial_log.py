#!/usr/bin/env python3
"""实验四 LIS3DSH 串口数据记录脚本.

把 EXP4 板子通过 USART2 上传的数据行解析成 CSV，便于贴进实验报告或画曲线。

用法:
    python tools/serial_log.py --list
    python tools/serial_log.py --port COM5 --out data.csv
    python tools/serial_log.py --port COM5 --seconds 60 --quiet
    python tools/serial_log.py --selftest      # 不接硬件，验证解析规则

数据行格式（main.c 的 Sensor_Report）:
    09:00:01  X=+0012 Y=-0008 Z=+0996 mg  |a|= 996 mg  +Z

CSV 列: time_rtc, x_mg, y_mg, z_mg, mag_mg, axis
"""

import argparse
import re
import sys
import time

LINE_RE = re.compile(
    r"^(?P<t>\d{2}:\d{2}:\d{2})\s+"
    r"X=(?P<x>[+-]\d+)\s+Y=(?P<y>[+-]\d+)\s+Z=(?P<z>[+-]\d+)\s*mg\s+"
    r"\|a\|=\s*(?P<mag>\d+)\s*mg\s+(?P<axis>\S+)\s*$"
)


def parse_line(line):
    """返回 dict 或 None（不是数据行/格式不符）。"""
    m = LINE_RE.match(line.strip())
    if not m:
        return None
    return {
        "time_rtc": m.group("t"),
        "x_mg": int(m.group("x")),
        "y_mg": int(m.group("y")),
        "z_mg": int(m.group("z")),
        "mag_mg": int(m.group("mag")),
        "axis": m.group("axis"),
    }


def selftest():
    samples = [
        "09:00:01  X=+0012 Y=-0008 Z=+0996 mg  |a|= 996 mg  +Z",
        "23:59:59  X=+0000 Y=+0000 Z=-1000 mg  |a|=1000 mg  -Z",
        "[STAT] drdy=1003 int2=0 rd_err=0",
        "[EVT] FREE-FALL  |a|=123 mg",
        "garbage",
    ]
    expected = [True, True, False, False, False]
    ok = True
    for s, exp in zip(samples, expected):
        got = parse_line(s) is not None
        ok = ok and (got == exp)
        print(f"{'OK ' if got == exp else 'BAD'}  {s}")
    print("SELFTEST", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def list_ports():
    try:
        from serial.tools import list_ports as lp
    except ImportError:
        print("需要 pyserial: python -m pip install pyserial", file=sys.stderr)
        return 1
    ports = list(lp.comports())
    if not ports:
        print("没有找到串口设备")
        return 1
    for p in ports:
        print(f"{p.device:10s} {p.description}")
    return 0


def run(port, baud, out_path, seconds, quiet):
    try:
        import serial
    except ImportError:
        print("需要 pyserial: python -m pip install pyserial", file=sys.stderr)
        return 1

    ser = serial.Serial(port, baud, timeout=1)
    print(f"已打开 {port} @ {baud} 8N1，Ctrl+C 结束", file=sys.stderr)

    rows = 0
    t0 = time.time()
    f = open(out_path, "w", encoding="utf-8", newline="") if out_path else None
    if f:
        f.write("time_rtc,x_mg,y_mg,z_mg,mag_mg,axis\n")

    try:
        while True:
            if seconds and (time.time() - t0) >= seconds:
                break
            raw = ser.readline()
            if not raw:
                continue
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if not quiet:
                print(line)
            rec = parse_line(line)
            if rec:
                rows += 1
                if f:
                    f.write("{time_rtc},{x_mg},{y_mg},{z_mg},{mag_mg},{axis}\n".format(**rec))
    except KeyboardInterrupt:
        pass
    finally:
        ser.close()
        if f:
            f.close()
            print(f"\n已保存 {rows} 行到 {out_path}", file=sys.stderr)
        else:
            print(f"\n共解析 {rows} 行", file=sys.stderr)
    return 0


def main():
    ap = argparse.ArgumentParser(description="LIS3DSH 串口数据记录/CSV 导出")
    ap.add_argument("--port", help="串口号，如 COM5")
    ap.add_argument("--baud", type=int, default=9600)
    ap.add_argument("--out", default="exp4_data.csv", help="CSV 输出路径（默认 exp4_data.csv）")
    ap.add_argument("--seconds", type=float, default=0, help="采集时长，0 = 一直采到 Ctrl+C")
    ap.add_argument("--quiet", action="store_true", help="不打印原始行")
    ap.add_argument("--list", action="store_true", help="列出可用串口")
    ap.add_argument("--selftest", action="store_true", help="离线验证解析规则")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if args.list or not args.port:
        return list_ports()
    return run(args.port, args.baud, args.out, args.seconds, args.quiet)


if __name__ == "__main__":
    raise SystemExit(main())
