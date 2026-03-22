#!/usr/bin/env python3
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideSwiftBar>true</swiftbar.hideSwiftBar>
"""
Claude Code Token Usage - SwiftBar Plugin
30秒ごとにメニューバーでトークン使用率を表示
"""

import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))
CLAUDE_DIR = Path.home() / ".claude" / "projects"
CONFIG_FILE = Path.home() / ".config" / "token_reader" / "config.json"

PLAN_LIMITS = {
    "pro": {"5h": 45_000_000, "weekly": 45_000_000 * 34},
    "max5": {"5h": 135_000_000, "weekly": 135_000_000 * 34},
    "max20": {"5h": 540_000_000, "weekly": 540_000_000 * 34},
}


def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def get_current_window(config, now):
    if "window_anchor" in config:
        anchor = datetime.fromisoformat(config["window_anchor"])
        elapsed = (now - anchor).total_seconds()
        n = int(elapsed // (5 * 3600))
        ws = anchor + timedelta(seconds=n * 5 * 3600)
        return ws, ws + timedelta(hours=5)
    elif "subscription_start" in config:
        anchor = datetime.fromisoformat(config["subscription_start"])
        elapsed = (now - anchor).total_seconds()
        n = int(elapsed // (5 * 3600))
        ws = anchor + timedelta(seconds=n * 5 * 3600)
        return ws, ws + timedelta(hours=5)
    else:
        h = (now.hour // 5) * 5
        ws = now.replace(hour=h, minute=0, second=0, microsecond=0)
        return ws, ws + timedelta(hours=5)


def get_current_week(config, now):
    if "weekly_reset_weekday" in config:
        wd = config["weekly_reset_weekday"]
        h = config.get("weekly_reset_hour", 0)
        m = config.get("weekly_reset_minute", 0)
        days_since = (now.weekday() - wd) % 7
        last = now - timedelta(days=days_since)
        last = last.replace(hour=h, minute=m, second=0, microsecond=0)
        if last > now:
            last -= timedelta(days=7)
        return last, last + timedelta(days=7)
    elif "subscription_start" in config:
        anchor = datetime.fromisoformat(config["subscription_start"])
        elapsed = (now - anchor).total_seconds()
        n = int(elapsed // (7 * 86400))
        ws = anchor + timedelta(seconds=n * 7 * 86400)
        return ws, ws + timedelta(days=7)
    else:
        ws = now - timedelta(days=now.weekday())
        ws = ws.replace(hour=0, minute=0, second=0, microsecond=0)
        return ws, ws + timedelta(days=7)


def parse_tokens():
    records = []
    if not CLAUDE_DIR.exists():
        return records

    for pd in CLAUDE_DIR.iterdir():
        if not pd.is_dir():
            continue
        for f in pd.glob("*.jsonl"):
            try:
                with open(f) as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            e = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if e.get("type") != "assistant":
                            continue
                        msg = e.get("message", {})
                        usage = msg.get("usage")
                        if not usage:
                            continue
                        ts_str = e.get("timestamp", "")
                        try:
                            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        except (ValueError, AttributeError):
                            continue
                        local_ts = ts.astimezone(JST)
                        inp = usage.get("input_tokens", 0) + usage.get("cache_creation_input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
                        out = usage.get("output_tokens", 0)
                        records.append({"local_timestamp": local_ts, "total_tokens": inp + out})
            except Exception:
                continue
    return records


def color_for_pct(pct):
    if pct >= 90:
        return "#FF4444"
    elif pct >= 70:
        return "#FFB800"
    elif pct >= 50:
        return "#FFFFFF"
    else:
        return "#88CC88"


def main():
    config = load_config()
    plan = config.get("plan", "pro")
    limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["pro"])

    now = datetime.now(JST)
    records = parse_tokens()

    # 5h window
    ws, we = get_current_window(config, now)
    w_tokens = sum(r["total_tokens"] for r in records if ws <= r["local_timestamp"] < we)
    w_pct = min(100, int(w_tokens / limits["5h"] * 100)) if limits["5h"] > 0 else 0

    # Weekly
    wks, wke = get_current_week(config, now)
    wk_tokens = sum(r["total_tokens"] for r in records if wks <= r["local_timestamp"] < wke)
    wk_pct = min(100, int(wk_tokens / limits["weekly"] * 100)) if limits["weekly"] > 0 else 0

    # Time remaining
    w_remaining = we - now
    w_h = int(w_remaining.total_seconds() // 3600)
    w_m = int((w_remaining.total_seconds() % 3600) // 60)

    wk_remaining = wke - now
    wk_d = wk_remaining.days
    wk_h = int((wk_remaining.total_seconds() % 86400) // 3600)

    # Menu bar title
    w_color = color_for_pct(w_pct)
    wk_color = color_for_pct(wk_pct)

    # SwiftBar supports SF Symbols
    print(f"☁ {w_pct}% | {wk_pct}% | sfimage=cloud.fill color={w_color}")
    print("---")

    # Dropdown details
    print(f"Claude Code Usage ({plan.upper()}) | size=14 font=Menlo-Bold")
    print("---")

    # 5h window section
    print(f"⏱ 5時間ウィンドウ ({ws.strftime('%H:%M')}〜{we.strftime('%H:%M')}) | size=13 font=Menlo-Bold")
    bar_w = 20
    filled_w = int(bar_w * w_pct / 100)
    bar_str_w = "█" * filled_w + "░" * (bar_w - filled_w)
    print(f"  {bar_str_w} {w_pct}% | font=Menlo size=12 color={w_color}")
    print(f"  使用: {w_tokens:,} / {limits['5h']:,} | font=Menlo size=11")
    print(f"  残量: {limits['5h'] - w_tokens:,} tokens | font=Menlo size=11 color={w_color}")
    print(f"  リセットまで: {w_h}h {w_m:02d}m | font=Menlo size=11")
    print("---")

    # Weekly section
    day_names = ["月", "火", "水", "木", "金", "土", "日"]
    reset_day = day_names[wke.weekday()] if wke else ""
    print(f"📅 週間 ({wks.strftime('%m/%d')}〜{wke.strftime('%m/%d')} {reset_day}) | size=13 font=Menlo-Bold")
    filled_wk = int(bar_w * wk_pct / 100)
    bar_str_wk = "█" * filled_wk + "░" * (bar_w - filled_wk)
    print(f"  {bar_str_wk} {wk_pct}% | font=Menlo size=12 color={wk_color}")
    print(f"  使用: {wk_tokens:,} / {limits['weekly']:,} | font=Menlo size=11")
    print(f"  残量: {limits['weekly'] - wk_tokens:,} tokens | font=Menlo size=11 color={wk_color}")
    print(f"  リセットまで: {wk_d}d {wk_h}h | font=Menlo size=11")
    print("---")

    # Actions
    print(f"最終更新: {now.strftime('%H:%M:%S')} | size=10 color=gray")
    print("---")
    home = Path.home()
    # token_reader.py is expected in the same directory as this plugin,
    # or in the original install location
    script_dir = Path(__file__).resolve().parent
    tr_path = script_dir / "token_reader.py"
    if not tr_path.exists():
        # Fallback: check config for install path
        tr_path = home / "Desktop" / "dev" / "Token_Reader" / "token_reader.py"
    print(f"モニターを開く | bash=/usr/bin/python3 param1={tr_path} param2=monitor terminal=true")
    print(f"設定をリセット | bash=/bin/rm param1=-f param2={home}/.config/token_reader/config.json terminal=false refresh=true")


if __name__ == "__main__":
    main()
