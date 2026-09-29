"""
ดึงราคาปาล์ม 3 ตลาด แล้วบันทึกเป็น JSON ให้หน้าเว็บอ่าน
  - NCDEX:CPO   (TradingView)  Crude Palm Oil - Kandla Spot  INR / 10 kg
  - MYX:FCPO1!  (TradingView)  Bursa Malaysia CPO Futures   MYR / ton
  - DCE P0      (Sina Finance) Dalian Palm Olein Futures    CNY / ton

นิยาม (เวลาไทย Asia/Bangkok):
  Open  = ราคาเปิดของแท่ง 15 นาทีแรกที่เริ่ม >= 09:45
  Close = ราคาปิดของแท่ง 15 นาทีสุดท้ายที่เริ่ม < 17:15  (คือราคา ณ 17:15 หรือราคาล่าสุดก่อนหน้า)
  ถ้าวันไหนไม่มีข้อมูล 15 นาที (ย้อนหลังเกินที่ API ให้) จะใช้ราคา Open/Close รายวันแทน และติดป้าย src="d"

ใช้งาน:  pip install websocket-client requests
         python scripts/fetch_prices.py
"""
from __future__ import annotations

import json
import random
import re
import string
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import websocket  # websocket-client

TH = ZoneInfo("Asia/Bangkok")
WIN_START = (9, 45)
WIN_END = (17, 15)
KEEP_DAYS = 400          # เก็บแท่ง intraday ย้อนหลังกี่วัน
TABLE_DAYS = 366         # ตารางรายวันย้อนหลังกี่วัน
DATA_DIR = Path(__file__).resolve().parent.parent / "public" / "data"

MARKETS = [
    {
        "key": "ncdex",
        "name": "NCDEX CPO Kandla Spot",
        "symbol": "NCDEX:CPO",
        "source": "tradingview",
        "currency": "INR",
        "unit": "INR/10kg",
        "tz": "Asia/Kolkata",
    },
    {
        "key": "fcpo",
        "name": "Bursa Malaysia FCPO (สัญญาใกล้สุด)",
        "symbol": "MYX:FCPO1!",
        "source": "tradingview",
        "currency": "MYR",
        "unit": "MYR/ton",
        "tz": "Asia/Kuala_Lumpur",
    },
    {
        "key": "dalian",
        "name": "Dalian Palm Olein (สัญญาหลัก P0)",
        "symbol": "P0",
        "source": "sina",
        "currency": "CNY",
        "unit": "CNY/ton",
        "tz": "Asia/Shanghai",
    },
]


# ---------------------------------------------------------------- TradingView
def _frame(m: str, p: list) -> str:
    s = json.dumps({"m": m, "p": p}, separators=(",", ":"))
    return f"~m~{len(s)}~m~{s}"


def tv_bars(symbol: str, interval: str, n_bars: int = 5000, more_pages: int = 1, timeout: int = 45) -> list[list]:
    """คืน [[ts_utc, o, h, l, c, v], ...] จาก TradingView (ไม่ต้อง login, ข้อมูลอาจดีเลย์ ~15 นาที)"""
    ws = websocket.create_connection(
        "wss://data.tradingview.com/socket.io/websocket",
        header={"Origin": "https://www.tradingview.com", "User-Agent": "Mozilla/5.0"},
        timeout=timeout,
    )
    cs = "cs_" + "".join(random.choices(string.ascii_lowercase + string.digits, k=12))
    sym = json.dumps({"symbol": symbol, "adjustment": "splits", "session": "regular"}, separators=(",", ":"))
    for m, p in [
        ("set_auth_token", ["unauthorized_user_token"]),
        ("chart_create_session", [cs, ""]),
        ("resolve_symbol", [cs, "sym1", "=" + sym]),
        ("create_series", [cs, "s1", "s1", "sym1", interval, n_bars]),
    ]:
        ws.send(_frame(m, p))

    bars: dict[int, list] = {}
    completed = 0
    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            raw = ws.recv()
            for part in re.split(r"~m~\d+~m~", raw):
                if not part:
                    continue
                if part.startswith("~h~"):
                    ws.send(f"~m~{len(part)}~m~{part}")
                    continue
                try:
                    j = json.loads(part)
                except ValueError:
                    continue
                m = j.get("m")
                if m in ("symbol_error", "series_error", "critical_error"):
                    raise RuntimeError(f"TradingView {m}: {j.get('p')}")
                if m in ("timescale_update", "du"):
                    s = j["p"][1].get("s1") or {}
                    for b in s.get("s", []):
                        v = b["v"]
                        bars[int(v[0])] = [int(v[0])] + [float(x) for x in v[1:5]] + [float(v[5]) if len(v) > 5 else 0.0]
                if m == "series_completed":
                    completed += 1
                    if completed <= more_pages:
                        ws.send(_frame("request_more_data", [cs, "s1", n_bars]))
                    else:
                        return [bars[k] for k in sorted(bars)]
        raise TimeoutError(f"TradingView timeout ({symbol} {interval}), got {len(bars)} bars")
    finally:
        ws.close()


# ---------------------------------------------------------------- Sina (Dalian)
SINA = "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20t=/InnerFuturesNewService.{fn}?symbol={sym}{extra}"
SINA_HEADERS = {"Referer": "https://finance.sina.com.cn/", "User-Agent": "Mozilla/5.0"}


def _sina(fn: str, sym: str, extra: str = "") -> list[dict]:
    r = requests.get(SINA.format(fn=fn, sym=sym, extra=extra), headers=SINA_HEADERS, timeout=30)
    r.raise_for_status()
    m = re.search(r"\((\[.*\])\)", r.text, re.S)
    return json.loads(m.group(1)) if m else []


def sina_15m(sym: str) -> list[list]:
    """Sina ใส่เวลา 'ปิดแท่ง' (CST) -> แปลงเป็นเวลาเริ่มแท่ง UTC"""
    cst = ZoneInfo("Asia/Shanghai")
    out = []
    for x in _sina("getFewMinLine", sym, "&type=15"):
        end = datetime.strptime(x["d"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=cst)
        ts = int((end - timedelta(minutes=15)).timestamp())
        out.append([ts, float(x["o"]), float(x["h"]), float(x["l"]), float(x["c"]), float(x["v"])])
    return out


def sina_daily(sym: str) -> dict[str, dict]:
    return {
        x["d"]: {"o": float(x["o"]), "h": float(x["h"]), "l": float(x["l"]), "c": float(x["c"])}
        for x in _sina("getDailyKLine", sym)
    }


def tv_daily(symbol: str, tz: str) -> dict[str, dict]:
    z = ZoneInfo(tz)
    out = {}
    for ts, o, h, l, c, _ in tv_bars(symbol, "1D", 400, more_pages=0):
        # +12 ชม. กันกรณีแท่งรายวันเริ่มที่ภาคกลางคืนของวันก่อน (FCPO เปิด 21:00)
        d = (datetime.fromtimestamp(ts, timezone.utc) + timedelta(hours=12)).astimezone(z).date().isoformat()
        out[d] = {"o": o, "h": h, "l": l, "c": c}
    return out


# ---------------------------------------------------------------- คำนวณ
def in_window(ts: int) -> bool:
    t = datetime.fromtimestamp(ts, TH)
    hm = (t.hour, t.minute)
    return t.weekday() < 5 and WIN_START <= hm < WIN_END


def build_daily(bars: list[list], daily_fallback: dict[str, dict], old_rows: list[dict] | None = None) -> list[dict]:
    by_day: dict[str, list] = {}
    for b in bars:
        d = datetime.fromtimestamp(b[0], TH).date().isoformat()
        by_day.setdefault(d, []).append(b)

    rows = {}
    for d, bs in by_day.items():
        bs.sort(key=lambda x: x[0])
        rows[d] = {
            "d": d,
            "o": bs[0][1],
            "h": max(x[2] for x in bs),
            "l": min(x[3] for x in bs),
            "c": bs[-1][4],
            "t_open": datetime.fromtimestamp(bs[0][0], TH).strftime("%H:%M"),
            "t_close": (datetime.fromtimestamp(bs[-1][0], TH) + timedelta(minutes=15)).strftime("%H:%M"),
            "src": "i",
        }
    # แถวเดิมที่คำนวณจาก 15 นาทีไว้แล้ว (แท่งอาจหมดอายุจาก API) -> เก็บไว้ตามเดิม
    for r in old_rows or []:
        if r["d"] not in rows and r.get("src") == "i":
            rows[r["d"]] = {k: r.get(k) for k in ("d", "o", "h", "l", "c", "t_open", "t_close", "src")}
    for d, v in daily_fallback.items():
        if d not in rows and datetime.fromisoformat(d).weekday() < 5:
            rows[d] = {"d": d, **v, "t_open": None, "t_close": None, "src": "d"}
    for r in old_rows or []:
        if r["d"] not in rows:
            rows[r["d"]] = {k: r.get(k) for k in ("d", "o", "h", "l", "c", "t_open", "t_close", "src")}

    cutoff = (datetime.now(TH) - timedelta(days=TABLE_DAYS)).date().isoformat()
    out = [rows[d] for d in sorted(rows) if d >= cutoff]
    prev = None
    for r in out:
        r["chg"] = round(r["c"] - r["o"], 4)
        r["chg_pct"] = round((r["c"] - r["o"]) / r["o"] * 100, 3) if r["o"] else None
        r["prev_chg_pct"] = round((r["c"] - prev) / prev * 100, 3) if prev else None
        prev = r["c"]
    return out


def update_market(mk: dict) -> dict:
    path = DATA_DIR / f"{mk['key']}.json"
    old = json.loads(path.read_text("utf-8")) if path.exists() else {}
    old_bars = {b[0]: b for b in old.get("bars", [])}

    if mk["source"] == "tradingview":
        new_bars = tv_bars(mk["symbol"], "15", 5000, more_pages=1)
        daily = tv_daily(mk["symbol"], mk["tz"])
    else:
        new_bars = sina_15m(mk["symbol"])
        daily = sina_daily(mk["symbol"])

    for b in new_bars:
        if in_window(b[0]):
            old_bars[b[0]] = b  # ข้อมูลใหม่ทับของเก่า (แท่งล่าสุดอาจยังไม่ปิด)
    cutoff = int((datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).timestamp())
    bars = [old_bars[k] for k in sorted(old_bars) if k >= cutoff]

    out = {
        **{k: mk[k] for k in ("key", "name", "symbol", "source", "currency", "unit")},
        "window": "09:45-17:15 Asia/Bangkok",
        "updated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "daily": build_daily(bars, daily, old.get("daily", [])),
        "bars": bars,
    }
    path.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), "utf-8")
    return out


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ok = 0
    for mk in MARKETS:
        try:
            d = update_market(mk)
            last = d["daily"][-1] if d["daily"] else {}
            print(f"[OK] {mk['key']:7s} bars={len(d['bars']):5d} days={len(d['daily']):3d} last={last.get('d')} O={last.get('o')} C={last.get('c')}")
            ok += 1
        except Exception as e:  # ตลาดหนึ่งพัง ตลาดอื่นยังอัปเดตต่อ
            print(f"[ERR] {mk['key']}: {e}", file=sys.stderr)
    (DATA_DIR / "meta.json").write_text(
        json.dumps({"updated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "markets": [m["key"] for m in MARKETS]}), "utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
