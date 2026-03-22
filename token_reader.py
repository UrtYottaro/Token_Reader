#!/usr/bin/env python3
"""Claude Code Token Usage Reader - トークン使用量を可視化するCLIツール"""

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from rich.console import Console
    from rich.table import Table
    from rich.live import Live
    from rich.panel import Panel
    from rich.progress import BarColumn, Progress, TextColumn, TaskProgressColumn
    from rich.layout import Layout
    from rich.text import Text
    from rich import box
except ImportError:
    print("Error: 'rich' package is required. Install it with: pip install rich")
    sys.exit(1)

console = Console()

# Claude model pricing (USD per 1M tokens)
MODEL_PRICING = {
    "claude-opus-4-6":   {"input": 15.0, "output": 75.0},
    "claude-opus-4-5":   {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-6": {"input": 3.0,  "output": 15.0},
    "claude-sonnet-4-5": {"input": 3.0,  "output": 15.0},
    "claude-sonnet-4-0": {"input": 3.0,  "output": 15.0},
    "claude-haiku-4-5":  {"input": 0.80, "output": 4.0},
    "claude-haiku-3-5":  {"input": 0.80, "output": 4.0},
}

# Default pricing for unknown models
DEFAULT_PRICING = {"input": 3.0, "output": 15.0}

# Plan definitions
PLANS = {
    "free": {
        "label": "Free",
        "price": "$0/月",
        "5h_limit": 0,
        "weekly_limit": 0,
        "description": "基本的なアクセス（レート制限あり）",
    },
    "pro": {
        "label": "Pro",
        "price": "$20/月",
        "5h_limit": 45_000_000,
        "weekly_limit": 45_000_000 * 34,  # ~34 windows/week
        "description": "標準的な開発者向け",
    },
    "max5": {
        "label": "Max 5x",
        "price": "$100/月",
        "5h_limit": 135_000_000,
        "weekly_limit": 135_000_000 * 34,
        "description": "ヘビーユーザー向け（Pro の 5 倍）",
    },
    "max20": {
        "label": "Max 20x",
        "price": "$200/月",
        "5h_limit": 540_000_000,
        "weekly_limit": 540_000_000 * 34,
        "description": "チーム・大規模開発向け（Pro の 20 倍）",
    },
}

# Backwards-compatible shortcuts
PLAN_LIMITS = {k: v["5h_limit"] for k, v in PLANS.items() if v["5h_limit"] > 0}
WEEKLY_LIMITS = {k: v["weekly_limit"] for k, v in PLANS.items() if v["weekly_limit"] > 0}

CLAUDE_DIR = Path.home() / ".claude" / "projects"
CONFIG_DIR = Path.home() / ".config" / "token_reader"
CONFIG_FILE = CONFIG_DIR / "config.json"
JST = timezone(timedelta(hours=9))


def load_config() -> dict:
    """Load configuration from file."""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_config(config: dict):
    """Save configuration to file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def ensure_config() -> dict:
    """Ensure config is set up. Run wizard if not."""
    config = load_config()
    if "subscription_start" not in config or "plan" not in config:
        config = _run_setup_wizard()
    return config


def get_subscription_start() -> datetime:
    """Get subscription start time from config, or run setup wizard."""
    config = ensure_config()
    return datetime.fromisoformat(config["subscription_start"])


def _run_setup_wizard() -> dict:
    """Interactive first-time setup wizard."""
    config = load_config()

    console.print()
    console.print(Panel(
        "[bold]Token Reader を使うには初期設定が必要です。[/bold]\n"
        "[dim]claude.ai → 設定 → 請求 の情報を参照してください。[/dim]",
        title="[bold cyan]初期設定ウィザード[/bold cyan]",
        border_style="cyan",
        padding=(1, 2),
    ))
    console.print()

    # ── Step 1: Plan selection ──
    console.print("[bold]1. プランを選択してください:[/bold]")
    console.print("   [dim]1[/dim]. Free        ($0/月)")
    console.print("   [dim]2[/dim]. Pro         ($20/月)")
    console.print("   [dim]3[/dim]. Max 5x      ($100/月)")
    console.print("   [dim]4[/dim]. Max 20x     ($200/月)")
    console.print()

    plan_map = {"1": "free", "2": "pro", "3": "max5", "4": "max20"}
    while True:
        try:
            choice = input("   番号を入力 (1-4): ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]キャンセルしました。[/dim]")
            sys.exit(0)

        if choice in plan_map:
            config["plan"] = plan_map[choice]
            console.print(f"   → [green]{PLANS[config['plan']]['label']}[/green] を選択\n")
            break
        console.print("   [red]1〜4の番号を入力してください。[/red]")

    # ── Step 2: Subscription start date ──
    if config["plan"] == "free":
        # Free plan: use earliest log or now
        earliest = _detect_earliest_log()
        if earliest:
            config["subscription_start"] = earliest.isoformat()
        else:
            now = datetime.now(JST)
            config["subscription_start"] = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        config["auto_detected"] = True
        console.print("[dim]Free プランのため、契約開始日は自動設定しました。[/dim]\n")
    else:
        console.print("[bold]2. 有料プランの契約開始日を入力してください:[/bold]")
        console.print("   [dim]claude.ai → 設定 → 請求 → 請求書 の最も古い日付を入力[/dim]")
        console.print("   [dim]形式: YYYY-MM-DD (例: 2026-03-05)[/dim]")
        console.print()

        while True:
            try:
                date_input = input("   契約開始日: ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]キャンセルしました。[/dim]")
                sys.exit(0)

            for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"]:
                try:
                    dt = datetime.strptime(date_input, fmt)
                    dt = dt.replace(tzinfo=JST)
                    config["subscription_start"] = dt.isoformat()
                    config["auto_detected"] = False
                    console.print(f"   → [green]{dt.strftime('%Y-%m-%d')}[/green] に設定\n")
                    break
                except ValueError:
                    continue
            else:
                console.print("   [red]正しい日付形式で入力してください (例: 2026-03-05)[/red]")
                continue
            break

        # ── Step 3: 5h window reset time ──
        console.print("[bold]3. 5時間ウィンドウのリセット時刻を確認してください:[/bold]")
        console.print("   [dim]claude.ai → 設定 → 使用量 → 「現在のセッション」の[/dim]")
        console.print("   [dim]「○時間○分後にリセット」から次のリセット時刻を入力[/dim]")
        console.print("   [dim]形式: HH:MM (例: 17:00)[/dim]")
        console.print("   [dim]スキップする場合は Enter を押してください（契約日から自動計算）[/dim]")
        console.print()

        while True:
            try:
                reset_input = input("   次の5hリセット時刻: ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]キャンセルしました。[/dim]")
                sys.exit(0)

            if not reset_input:
                console.print("   → [dim]契約日から自動計算します[/dim]\n")
                break

            try:
                reset_h, reset_m = map(int, reset_input.split(":"))
                if not (0 <= reset_h <= 23 and 0 <= reset_m <= 59):
                    raise ValueError
                # Calculate anchor: the reset time is a window END,
                # so the window START is 5 hours before.
                # Anchor must align so that this reset time falls on a window boundary.
                now = datetime.now(JST)
                next_reset = now.replace(hour=reset_h, minute=reset_m, second=0, microsecond=0)
                if next_reset <= now:
                    next_reset += timedelta(days=1)
                # Window start = reset - 5h, anchor aligns to this
                window_start = next_reset - timedelta(hours=5)
                config["window_anchor"] = window_start.isoformat()
                console.print(f"   → リセット時刻 [green]{reset_input}[/green] → 現在のウィンドウ: {window_start.strftime('%H:%M')}〜{next_reset.strftime('%H:%M')}\n")
                break
            except (ValueError, AttributeError):
                console.print("   [red]HH:MM 形式で入力してください (例: 17:00)[/red]")

        # ── Step 4: Weekly reset ──
        console.print("[bold]4. 週間制限のリセット日時を確認してください:[/bold]")
        console.print("   [dim]claude.ai → 設定 → 使用量 → 「週間制限」の[/dim]")
        console.print("   [dim]「○:○○ (曜日)にリセット」の曜日と時刻を入力[/dim]")
        console.print("   [dim]形式: 曜日 HH:MM (例: 木 17:00)[/dim]")
        console.print("   [dim]スキップする場合は Enter を押してください（契約日から自動計算）[/dim]")
        console.print()

        weekday_map = {"月": 0, "火": 1, "水": 2, "木": 3, "金": 4, "土": 5, "日": 6}

        while True:
            try:
                weekly_input = input("   週間リセット (曜日 HH:MM): ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]キャンセルしました。[/dim]")
                sys.exit(0)

            if not weekly_input:
                console.print("   → [dim]契約日から自動計算します[/dim]\n")
                break

            try:
                parts = weekly_input.split()
                if len(parts) == 2:
                    day_str, time_str = parts
                elif len(parts) == 1:
                    # Maybe just "木17:00" or "木 17:00"
                    day_str = parts[0][0]
                    time_str = parts[0][1:]
                else:
                    raise ValueError

                if day_str not in weekday_map:
                    raise ValueError(f"曜日が不正です: {day_str}")

                wk_h, wk_m = map(int, time_str.split(":"))
                if not (0 <= wk_h <= 23 and 0 <= wk_m <= 59):
                    raise ValueError

                target_weekday = weekday_map[day_str]
                config["weekly_reset_weekday"] = target_weekday
                config["weekly_reset_hour"] = wk_h
                config["weekly_reset_minute"] = wk_m

                day_names = ["月", "火", "水", "木", "金", "土", "日"]
                console.print(f"   → 週間リセット: 毎週[green]{day_names[target_weekday]}曜 {wk_h:02d}:{wk_m:02d}[/green]\n")
                break
            except (ValueError, IndexError, AttributeError):
                console.print("   [red]「曜日 HH:MM」形式で入力してください (例: 木 17:00)[/red]")

    # ── Save and confirm ──
    save_config(config)

    anchor = datetime.fromisoformat(config["subscription_start"])
    now = datetime.now(JST)

    if config["plan"] != "free":
        ws, we = get_current_window_from_config(config, now)
        wks, wke = get_current_week_from_config(config, now)

        console.print(Panel(
            f"[bold]プラン:[/bold]         {PLANS[config['plan']]['label']} ({PLANS[config['plan']]['price']})\n"
            f"[bold]契約開始日:[/bold]     {anchor.strftime('%Y-%m-%d')} JST\n"
            f"[bold]設定ファイル:[/bold]   {CONFIG_FILE}\n"
            f"\n"
            f"[bold]現在の5hウィンドウ:[/bold] {ws.strftime('%H:%M')}〜{we.strftime('%H:%M')}\n"
            f"[bold]週間リセット:[/bold]       {wke.strftime('%Y-%m-%d %H:%M')} ({_weekday_name(wke)})",
            title="[bold green]設定完了[/bold green]",
            border_style="green",
            padding=(1, 2),
        ))
    else:
        console.print(Panel(
            f"[bold]プラン:[/bold]       {PLANS[config['plan']]['label']}\n"
            f"[bold]設定ファイル:[/bold] {CONFIG_FILE}",
            title="[bold green]設定完了[/bold green]",
            border_style="green",
            padding=(1, 2),
        ))

    console.print("[dim]設定を変更するには: python3 token_reader.py init --plan pro --start 2026-03-05[/dim]\n")

    return config


def _detect_earliest_log():
    """Find the earliest timestamp in all JSONL logs."""
    earliest = None
    if not CLAUDE_DIR.exists():
        return None

    for project_dir in CLAUDE_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        for jsonl_file in project_dir.glob("*.jsonl"):
            try:
                with open(jsonl_file, "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        ts_str = entry.get("timestamp", "")
                        if not ts_str:
                            continue
                        try:
                            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                            if earliest is None or ts < earliest:
                                earliest = ts
                        except (ValueError, AttributeError):
                            continue
            except Exception:
                continue

    if earliest:
        return earliest.astimezone(JST)
    return None


def get_current_window(anchor, now):
    """Calculate current 5-hour window based on subscription anchor time.

    The 5-hour windows cycle continuously from the anchor time:
    anchor+0h ~ anchor+5h, anchor+5h ~ anchor+10h, etc.
    """
    elapsed = (now - anchor).total_seconds()
    window_seconds = 5 * 3600  # 5 hours
    windows_passed = int(elapsed // window_seconds)
    window_start = anchor + timedelta(seconds=windows_passed * window_seconds)
    window_end = window_start + timedelta(hours=5)
    return window_start, window_end


def get_current_week(anchor, now):
    """Calculate current weekly cycle based on subscription anchor time.

    The weekly cycle repeats every 7 days from the anchor.
    """
    elapsed = (now - anchor).total_seconds()
    week_seconds = 7 * 86400
    weeks_passed = int(elapsed // week_seconds)
    week_start = anchor + timedelta(seconds=weeks_passed * week_seconds)
    # Align to start of day
    week_start = week_start.replace(hour=anchor.hour, minute=anchor.minute, second=0, microsecond=0)
    week_end = week_start + timedelta(days=7)
    return week_start, week_end


def _weekday_name(dt):
    """Return Japanese weekday name."""
    names = ["月", "火", "水", "木", "金", "土", "日"]
    return names[dt.weekday()]


def get_current_window_from_config(config, now):
    """Calculate 5h window using window_anchor if set, otherwise subscription_start."""
    if "window_anchor" in config:
        anchor = datetime.fromisoformat(config["window_anchor"])
        # window_anchor is a specific window start time; 5h windows cycle from it
        elapsed = (now - anchor).total_seconds()
        window_seconds = 5 * 3600
        windows_passed = int(elapsed // window_seconds)
        ws = anchor + timedelta(seconds=windows_passed * window_seconds)
        we = ws + timedelta(hours=5)
        return ws, we
    else:
        anchor = datetime.fromisoformat(config.get("subscription_start", now.isoformat()))
        return get_current_window(anchor, now)


def get_current_week_from_config(config, now):
    """Calculate weekly cycle using weekly_reset settings if set."""
    if "weekly_reset_weekday" in config:
        target_wd = config["weekly_reset_weekday"]
        h = config.get("weekly_reset_hour", 0)
        m = config.get("weekly_reset_minute", 0)

        # Find the most recent reset time (which is the start of the current week)
        days_since_reset = (now.weekday() - target_wd) % 7
        last_reset = now - timedelta(days=days_since_reset)
        last_reset = last_reset.replace(hour=h, minute=m, second=0, microsecond=0)
        if last_reset > now:
            last_reset -= timedelta(days=7)
        next_reset = last_reset + timedelta(days=7)
        return last_reset, next_reset
    else:
        anchor = datetime.fromisoformat(config.get("subscription_start", now.isoformat()))
        return get_current_week(anchor, now)


def get_pricing(model: str) -> dict:
    """Get pricing for a model, with fallback."""
    for key, pricing in MODEL_PRICING.items():
        if key in model:
            return pricing
    return DEFAULT_PRICING


def calc_cost(usage: dict, model: str) -> float:
    """Calculate cost in USD from usage data."""
    pricing = get_pricing(model)
    input_tokens = usage.get("input_tokens", 0)
    cache_creation = usage.get("cache_creation_input_tokens", 0)
    cache_read = usage.get("cache_read_input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)

    total_input = input_tokens + cache_creation + cache_read
    cost = (total_input * pricing["input"] / 1_000_000) + (output_tokens * pricing["output"] / 1_000_000)
    return cost


def parse_logs(since: str = None, until: str = None, project_filter: str = None):
    """Parse all JSONL log files and return structured records."""
    records = []

    if not CLAUDE_DIR.exists():
        console.print(f"[red]Error: {CLAUDE_DIR} not found[/red]")
        return records

    for project_dir in CLAUDE_DIR.iterdir():
        if not project_dir.is_dir():
            continue

        project_name = project_dir.name
        if project_filter and project_filter not in project_name:
            continue

        # Main session files
        for jsonl_file in project_dir.glob("*.jsonl"):
            _parse_jsonl(jsonl_file, project_name, records)

        # Subagent files
        for jsonl_file in project_dir.glob("*/subagents/*.jsonl"):
            _parse_jsonl(jsonl_file, project_name, records)

    # Apply date filters
    if since:
        since_date = datetime.strptime(since, "%Y%m%d").date()
        records = [r for r in records if r["date"] >= since_date]
    if until:
        until_date = datetime.strptime(until, "%Y%m%d").date()
        records = [r for r in records if r["date"] <= until_date]

    return records


def _parse_jsonl(jsonl_file: Path, project_name: str, records: list):
    """Parse a single JSONL file and append records."""
    try:
        with open(jsonl_file, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if entry.get("type") != "assistant":
                    continue

                msg = entry.get("message", {})
                usage = msg.get("usage")
                if not usage:
                    continue

                model = msg.get("model", "unknown")
                timestamp_str = entry.get("timestamp", "")
                session_id = entry.get("sessionId", "unknown")

                try:
                    ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    continue

                input_tokens = usage.get("input_tokens", 0)
                cache_creation = usage.get("cache_creation_input_tokens", 0)
                cache_read = usage.get("cache_read_input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)
                total_tokens = input_tokens + cache_creation + cache_read + output_tokens
                cost = calc_cost(usage, model)

                local_ts = ts.astimezone(JST)

                records.append({
                    "timestamp": ts,
                    "local_timestamp": local_ts,
                    "date": local_ts.date(),
                    "month": local_ts.strftime("%Y-%m"),
                    "session_id": session_id,
                    "project": project_name,
                    "model": model,
                    "input_tokens": input_tokens + cache_creation + cache_read,
                    "output_tokens": output_tokens,
                    "total_tokens": total_tokens,
                    "cost": cost,
                })
    except Exception:
        pass


def format_tokens(n: int) -> str:
    """Format token count with commas."""
    return f"{n:,}"


def format_cost(c: float) -> str:
    """Format cost in USD."""
    return f"${c:.2f}"


def cmd_daily(args):
    """Show daily token usage report."""
    records = parse_logs(args.since, args.until, args.project)
    if not records:
        console.print("[yellow]No usage data found.[/yellow]")
        return

    daily = defaultdict(lambda: {"tokens": 0, "cost": 0.0, "models": defaultdict(lambda: {"tokens": 0, "cost": 0.0})})
    for r in records:
        key = str(r["date"])
        daily[key]["tokens"] += r["total_tokens"]
        daily[key]["cost"] += r["cost"]
        daily[key]["models"][r["model"]]["tokens"] += r["total_tokens"]
        daily[key]["models"][r["model"]]["cost"] += r["cost"]

    if args.json:
        _output_json({k: {"tokens": v["tokens"], "cost": round(v["cost"], 2)} for k, v in sorted(daily.items())})
        return

    table = Table(title="Daily Token Usage", box=box.ROUNDED)
    table.add_column("Date", style="cyan")
    table.add_column("Tokens", justify="right", style="green")
    table.add_column("Cost (USD)", justify="right", style="yellow")

    if args.breakdown:
        table.add_column("Model Breakdown", style="dim")

    total_tokens = 0
    total_cost = 0.0

    for date_str in sorted(daily.keys()):
        d = daily[date_str]
        total_tokens += d["tokens"]
        total_cost += d["cost"]

        row = [date_str, format_tokens(d["tokens"]), format_cost(d["cost"])]
        if args.breakdown:
            breakdown = ", ".join(f"{m}: {format_tokens(v['tokens'])} ({format_cost(v['cost'])})" for m, v in d["models"].items())
            row.append(breakdown)

        table.add_row(*row)

    table.add_section()
    total_row = ["[bold]Total[/bold]", f"[bold]{format_tokens(total_tokens)}[/bold]", f"[bold]{format_cost(total_cost)}[/bold]"]
    if args.breakdown:
        total_row.append("")
    table.add_row(*total_row)

    console.print(table)
    _print_limits_summary(args, records)


def cmd_monthly(args):
    """Show monthly token usage report."""
    records = parse_logs(args.since, args.until, args.project)
    if not records:
        console.print("[yellow]No usage data found.[/yellow]")
        return

    monthly = defaultdict(lambda: {"tokens": 0, "cost": 0.0})
    for r in records:
        monthly[r["month"]]["tokens"] += r["total_tokens"]
        monthly[r["month"]]["cost"] += r["cost"]

    if args.json:
        _output_json({k: {"tokens": v["tokens"], "cost": round(v["cost"], 2)} for k, v in sorted(monthly.items())})
        return

    table = Table(title="Monthly Token Usage", box=box.ROUNDED)
    table.add_column("Month", style="cyan")
    table.add_column("Tokens", justify="right", style="green")
    table.add_column("Cost (USD)", justify="right", style="yellow")

    total_tokens = 0
    total_cost = 0.0

    for month in sorted(monthly.keys()):
        m = monthly[month]
        total_tokens += m["tokens"]
        total_cost += m["cost"]
        table.add_row(month, format_tokens(m["tokens"]), format_cost(m["cost"]))

    table.add_section()
    table.add_row("[bold]Total[/bold]", f"[bold]{format_tokens(total_tokens)}[/bold]", f"[bold]{format_cost(total_cost)}[/bold]")

    console.print(table)
    _print_limits_summary(args, records)


def cmd_session(args):
    """Show session-level token usage report."""
    records = parse_logs(args.since, args.until, args.project)
    if not records:
        console.print("[yellow]No usage data found.[/yellow]")
        return

    sessions = defaultdict(lambda: {"tokens": 0, "cost": 0.0, "project": "", "start": None, "end": None, "model": ""})
    for r in records:
        s = sessions[r["session_id"]]
        s["tokens"] += r["total_tokens"]
        s["cost"] += r["cost"]
        s["project"] = r["project"]
        s["model"] = r["model"]
        if s["start"] is None or r["local_timestamp"] < s["start"]:
            s["start"] = r["local_timestamp"]
        if s["end"] is None or r["local_timestamp"] > s["end"]:
            s["end"] = r["local_timestamp"]

    if args.json:
        out = {}
        for sid, v in sessions.items():
            out[sid] = {"tokens": v["tokens"], "cost": round(v["cost"], 2), "project": v["project"],
                        "start": v["start"].isoformat() if v["start"] else None}
        _output_json(out)
        return

    table = Table(title="Session Token Usage", box=box.ROUNDED)
    table.add_column("Session ID", style="cyan", max_width=12)
    table.add_column("Project", style="blue", max_width=30)
    table.add_column("Start", style="dim")
    table.add_column("Model", style="magenta")
    table.add_column("Tokens", justify="right", style="green")
    table.add_column("Cost (USD)", justify="right", style="yellow")

    total_tokens = 0
    total_cost = 0.0

    sorted_sessions = sorted(sessions.items(), key=lambda x: x[1]["start"] or datetime.min.replace(tzinfo=JST))
    for sid, s in sorted_sessions:
        total_tokens += s["tokens"]
        total_cost += s["cost"]
        start_str = s["start"].strftime("%Y-%m-%d %H:%M") if s["start"] else "N/A"
        short_project = s["project"].replace("-Users-yottaro-Desktop-dev-", "")
        table.add_row(sid[:12], short_project, start_str, s["model"], format_tokens(s["tokens"]), format_cost(s["cost"]))

    table.add_section()
    table.add_row("[bold]Total[/bold]", "", "", "", f"[bold]{format_tokens(total_tokens)}[/bold]", f"[bold]{format_cost(total_cost)}[/bold]")

    console.print(table)


def cmd_blocks(args):
    """Show 5-hour billing window usage."""
    records = parse_logs(args.since, args.until, args.project)
    if not records:
        console.print("[yellow]No usage data found.[/yellow]")
        return

    if args.live:
        _live_dashboard(args)
        return

    # Group by 5-hour windows based on config
    config = ensure_config()
    blocks = defaultdict(lambda: {"tokens": 0, "cost": 0.0})
    for r in records:
        ts = r["local_timestamp"]
        ws, _ = get_current_window_from_config(config, ts)
        key = ws.strftime("%Y-%m-%d %H:%M")
        blocks[key]["tokens"] += r["total_tokens"]
        blocks[key]["cost"] += r["cost"]

    if args.json:
        _output_json({k: {"tokens": v["tokens"], "cost": round(v["cost"], 2)} for k, v in sorted(blocks.items())})
        return

    plan = args.plan if hasattr(args, "plan") and args.plan else "pro"
    window_limit = PLAN_LIMITS.get(plan, PLAN_LIMITS["pro"])
    weekly_limit = WEEKLY_LIMITS.get(plan, WEEKLY_LIMITS["pro"])

    table = Table(title=f"5-Hour Billing Windows ({plan.upper()} Plan)", box=box.ROUNDED)
    table.add_column("Window Start", style="cyan")
    table.add_column("Tokens", justify="right", style="green")
    table.add_column("Limit", justify="right", style="dim")
    table.add_column("Usage %", justify="right")
    table.add_column("Cost (USD)", justify="right", style="yellow")

    total_tokens = 0
    total_cost = 0.0

    for key in sorted(blocks.keys()):
        b = blocks[key]
        total_tokens += b["tokens"]
        total_cost += b["cost"]
        pct = (b["tokens"] / window_limit) * 100 if window_limit > 0 else 0
        if pct >= 90:
            pct_style = "[bold red]"
        elif pct >= 70:
            pct_style = "[yellow]"
        else:
            pct_style = "[green]"
        pct_str = f"{pct_style}{pct:.1f}%{pct_style.replace('[', '[/')}"
        table.add_row(key, format_tokens(b["tokens"]), format_tokens(window_limit), pct_str, format_cost(b["cost"]))

    table.add_section()
    table.add_row("[bold]Total[/bold]", f"[bold]{format_tokens(total_tokens)}[/bold]", "", "", f"[bold]{format_cost(total_cost)}[/bold]")

    console.print(table)

    # Weekly summary
    now = datetime.now(JST)
    week_start, week_end = get_current_week_from_config(config, now)
    weekly_tokens = sum(r["total_tokens"] for r in records if week_start <= r["local_timestamp"] < week_end)
    weekly_cost = sum(r["cost"] for r in records if week_start <= r["local_timestamp"] < week_end)
    weekly_pct = (weekly_tokens / weekly_limit) * 100 if weekly_limit > 0 else 0

    if weekly_pct >= 90:
        w_color = "red"
    elif weekly_pct >= 70:
        w_color = "yellow"
    else:
        w_color = "green"

    bar_width = 30
    filled = int(bar_width * min(100, weekly_pct) / 100)
    bar = f"[{w_color}]{'█' * filled}[/{w_color}][dim]{'░' * (bar_width - filled)}[/dim]"

    weekly_panel = Panel(
        f"[bold]Plan:[/bold]           {plan.upper()}\n"
        f"[bold]5h Window Limit:[/bold] {format_tokens(window_limit)} tokens\n"
        f"[bold]Weekly Limit:[/bold]    {format_tokens(weekly_limit)} tokens (≈{WEEKLY_WINDOWS:.0f} windows)\n"
        f"\n"
        f"[bold]This Week:[/bold]       {format_tokens(weekly_tokens)} / {format_tokens(weekly_limit)}\n"
        f"[bold]Weekly Cost:[/bold]     {format_cost(weekly_cost)}\n"
        f"[bold]Usage:[/bold]           {bar} [{w_color}]{weekly_pct:.1f}%[/{w_color}]",
        title="[bold cyan]Token Limits Summary[/bold cyan]",
        border_style="cyan",
        padding=(1, 2),
    )
    console.print(weekly_panel)


def _get_plan(args):
    """Get plan from args or config."""
    config = load_config()
    if hasattr(args, "plan") and args.plan:
        return args.plan
    return config.get("plan", "pro")


def _live_dashboard(args):
    """Real-time live dashboard with auto-refresh."""
    config = ensure_config()
    plan = config.get("plan", _get_plan(args))
    window_limit = PLAN_LIMITS.get(plan, PLAN_LIMITS["pro"])
    weekly_limit = WEEKLY_LIMITS.get(plan, WEEKLY_LIMITS["pro"])

    try:
        with Live(console=console, refresh_per_second=1) as live:
            while True:
                records = parse_logs(project_filter=args.project if hasattr(args, "project") else None)
                now = datetime.now(JST)

                # ── Current 5-hour window (config-based) ──
                window_start, window_end = get_current_window_from_config(config, now)

                current_records = [r for r in records if window_start <= r["local_timestamp"] < window_end]

                window_tokens = sum(r["total_tokens"] for r in current_records)
                window_input = sum(r["input_tokens"] for r in current_records)
                window_output = sum(r["output_tokens"] for r in current_records)
                window_remaining = max(0, window_limit - window_tokens)
                window_pct = min(100.0, (window_tokens / window_limit) * 100) if window_limit > 0 else 0

                # ── Weekly usage (config-based) ──
                week_start, week_end = get_current_week_from_config(config, now)
                weekly_records = [r for r in records if week_start <= r["local_timestamp"] < week_end]
                weekly_tokens = sum(r["total_tokens"] for r in weekly_records)
                weekly_remaining = max(0, weekly_limit - weekly_tokens)
                weekly_pct = min(100.0, (weekly_tokens / weekly_limit) * 100) if weekly_limit > 0 else 0

                # ── Time remaining ──
                window_time_remaining = window_end - now
                w_hours_left = int(window_time_remaining.total_seconds() // 3600)
                w_mins_left = int((window_time_remaining.total_seconds() % 3600) // 60)

                weekly_time_remaining = week_end - now
                wk_days_left = weekly_time_remaining.days
                wk_hours_left = int((weekly_time_remaining.total_seconds() % 86400) // 3600)
                wk_mins_left = int((weekly_time_remaining.total_seconds() % 3600) // 60)

                # ── Progress bars ──
                bar_width = 40

                def _bar(pct):
                    filled = int(bar_width * min(100, pct) / 100)
                    if pct >= 90:
                        c = "red"
                    elif pct >= 70:
                        c = "yellow"
                    else:
                        c = "green"
                    return f"[{c}]{'█' * filled}[/{c}][dim]{'░' * (bar_width - filled)}[/dim]"

                # ── Remaining color based on usage % ──
                def _remaining_color(pct):
                    if pct >= 90:
                        return "red"
                    elif pct >= 70:
                        return "yellow"
                    else:
                        return "bold cyan"

                w_rc = _remaining_color(window_pct)
                wk_rc = _remaining_color(weekly_pct)

                # ── Date formats ──
                week_start_str = week_start.strftime("%m/%d/%Y")
                week_end_str = (week_end - timedelta(seconds=1)).strftime("%m/%d/%Y")

                # ── Build display ──
                content = (
                    f"\n"
                    f"[bold]━━━ ⏱  5時間ウィンドウ ({window_start.strftime('%H:%M')}〜{window_end.strftime('%H:%M')}) ━━━[/bold]\n"
                    f"   {_bar(window_pct)}\n"
                    f"   使用量: [bold]{format_tokens(window_tokens)}[/bold] / {format_tokens(window_limit)}"
                    f"　残量: [{w_rc}]{format_tokens(window_remaining)} tokens[/{w_rc}]\n"
                    f"   {window_end.strftime('%H:%M')}にリセット ({w_hours_left}h {w_mins_left:02d}m)"
                    f"　Input: {format_tokens(window_input)} / Output: {format_tokens(window_output)}\n"
                    f"\n"
                    f"[bold]━━━ 📅 今週の使用量 ({week_start_str}〜{week_end_str}) ━━━[/bold]\n"
                    f"   {_bar(weekly_pct)}\n"
                    f"   使用量: [bold]{format_tokens(weekly_tokens)}[/bold] / {format_tokens(weekly_limit)}"
                    f"　残量: [{wk_rc}]{format_tokens(weekly_remaining)} tokens[/{wk_rc}]\n"
                    f"   {week_end.strftime('%m/%d')} 00:00にリセット ({wk_days_left}d {wk_hours_left}h {wk_mins_left:02d}m)\n"
                    f"\n"
                    f"[dim]最終更新: {now.strftime('%Y-%m-%d %H:%M:%S')} JST[/dim]"
                )

                panel = Panel(
                    content,
                    title=f"[bold cyan]Claude Code Usage Monitor[/bold cyan]（{plan.upper()} Plan）",
                    subtitle="[dim]3秒ごと自動更新 | Ctrl+C で終了[/dim]",
                    border_style="cyan",
                    padding=(1, 2),
                )

                live.update(panel)
                time.sleep(3)

    except KeyboardInterrupt:
        console.print("\n[dim]Dashboard stopped.[/dim]")


def cmd_monitor(args):
    """Shortcut for real-time monitoring dashboard."""
    args.since = None
    args.until = None
    args.json = False
    args.live = True
    _live_dashboard(args)


def cmd_init(args):
    """Set or update subscription start time."""
    config = load_config()

    if args.start:
        # Parse user-provided start time
        try:
            # Accept formats: "2026-03-13", "2026-03-13 14:30", "20260313"
            for fmt in ["%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y%m%d", "%Y%m%d%H%M"]:
                try:
                    dt = datetime.strptime(args.start, fmt)
                    dt = dt.replace(tzinfo=JST)
                    break
                except ValueError:
                    continue
            else:
                console.print("[red]Error: 日付フォーマットが不正です。以下の形式で指定してください:[/red]")
                console.print("  2026-03-13")
                console.print("  2026-03-13 14:30")
                console.print("  20260313")
                return

            config["subscription_start"] = dt.isoformat()
            config["auto_detected"] = False
            save_config(config)
            console.print(f"[green]契約開始時刻を設定しました: {dt.strftime('%Y-%m-%d %H:%M')} JST[/green]")

        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            return

    if hasattr(args, "plan") and args.plan:
        config["plan"] = args.plan
        save_config(config)
        console.print(f"[green]プランを設定しました: {PLANS[args.plan]['label']}[/green]")

    if args.auto:
        # Auto-detect from logs
        earliest = _detect_earliest_log()
        if earliest:
            config["subscription_start"] = earliest.isoformat()
            config["auto_detected"] = True
            save_config(config)
            console.print(f"[green]ログから自動検出しました: {earliest.strftime('%Y-%m-%d %H:%M')} JST[/green]")
        else:
            console.print("[yellow]ログファイルが見つかりませんでした。[/yellow]")
            return

    # Show current config
    anchor = get_subscription_start()
    now = datetime.now(JST)
    config = load_config()
    ws, we = get_current_window_from_config(config, now)
    wks, wke = get_current_week_from_config(config, now)

    auto_label = " [dim](自動検出)[/dim]" if config.get("auto_detected") else " [dim](手動設定)[/dim]"

    panel = Panel(
        f"[bold]契約開始時刻:[/bold] {anchor.strftime('%Y-%m-%d %H:%M')} JST{auto_label}\n"
        f"[bold]設定ファイル:[/bold] {CONFIG_FILE}\n"
        f"\n"
        f"[bold]現在の5hウィンドウ:[/bold] {ws.strftime('%Y-%m-%d %H:%M')} 〜 {we.strftime('%H:%M')}\n"
        f"[bold]週間リセット:[/bold]       {wke.strftime('%Y-%m-%d %H:%M')} ({_weekday_name(wke)})",
        title="[bold cyan]Token Reader 設定[/bold cyan]",
        border_style="cyan",
        padding=(1, 2),
    )
    console.print(panel)


def cmd_plans(args):
    """Show plan comparison table and 5-hour window timetable."""
    config = ensure_config()
    anchor = datetime.fromisoformat(config["subscription_start"])
    now = datetime.now(JST)
    current_plan = config.get("plan", args.plan if hasattr(args, "plan") else "pro")

    # ── Plan comparison table ──
    table = Table(title="Claude Code プラン比較", box=box.ROUNDED)
    table.add_column("プラン", style="bold")
    table.add_column("月額", justify="right", style="yellow")
    table.add_column("5hウィンドウ上限", justify="right", style="green")
    table.add_column("週間上限", justify="right", style="green")
    table.add_column("説明", style="dim")

    for key, p in PLANS.items():
        marker = " ◀" if key == current_plan else ""
        plan_label = f"[bold cyan]{p['label']}{marker}[/bold cyan]" if key == current_plan else p["label"]
        limit_5h = format_tokens(p["5h_limit"]) if p["5h_limit"] > 0 else "制限あり"
        limit_wk = format_tokens(p["weekly_limit"]) if p["weekly_limit"] > 0 else "制限あり"
        table.add_row(plan_label, p["price"], limit_5h, limit_wk, p["description"])

    console.print(table)
    console.print()

    # ── 5-hour window timetable ──
    auto_label = "(自動検出)" if config.get("auto_detected") else "(手動設定)"
    console.print(f"[bold]契約開始: {anchor.strftime('%Y-%m-%d %H:%M')} JST {auto_label}[/bold]\n")

    timetable = Table(title="今日の5時間ウィンドウ時刻表", box=box.ROUNDED)
    timetable.add_column("#", style="dim", justify="right")
    timetable.add_column("開始", style="cyan")
    timetable.add_column("終了", style="cyan")
    timetable.add_column("状態", justify="center")

    # Generate all windows for today (around current time)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_end = today_start + timedelta(days=1)

    # Find the window that contains today_start
    ws_at_today, _ = get_current_window_from_config(config, today_start)
    ws = ws_at_today
    window_num = 1
    current_ws, current_we = get_current_window_from_config(config, now)

    while ws < tomorrow_end:
        we = ws + timedelta(hours=5)

        # Only show windows that overlap with today
        if we > today_start:
            if ws == current_ws:
                # Time remaining
                remaining = current_we - now
                h = int(remaining.total_seconds() // 3600)
                m = int((remaining.total_seconds() % 3600) // 60)
                status = f"[bold green]▶ 現在 (残り {h}h {m:02d}m)[/bold green]"
            elif ws > now:
                status = "[dim]予定[/dim]"
            else:
                status = "[dim]終了[/dim]"

            timetable.add_row(
                str(window_num),
                ws.strftime("%H:%M"),
                we.strftime("%H:%M" if we.date() == ws.date() else "%m/%d %H:%M"),
                status,
            )
            window_num += 1

        ws = we

    console.print(timetable)
    console.print()

    # ── Weekly cycle info ──
    week_start, week_end = get_current_week_from_config(config, now)
    weekly_remaining = week_end - now

    week_table = Table(title="週間サイクル", box=box.ROUNDED)
    week_table.add_column("項目", style="bold")
    week_table.add_column("値", style="cyan")

    week_table.add_row("現在の週間サイクル", f"{week_start.strftime('%Y-%m-%d %H:%M')} 〜 {week_end.strftime('%Y-%m-%d %H:%M')} JST")
    week_table.add_row("リセットまで", f"{weekly_remaining.days}d {int((weekly_remaining.total_seconds() % 86400) // 3600)}h {int((weekly_remaining.total_seconds() % 3600) // 60):02d}m")
    week_table.add_row("1週間のウィンドウ数", f"{7 * 24 // 5} 回 (= 168h / 5h)")

    console.print(week_table)


def _print_limits_summary(args, records):
    """Print token limits summary panel."""
    plan = args.plan if hasattr(args, "plan") and args.plan else "pro"
    window_limit = PLAN_LIMITS.get(plan, PLAN_LIMITS["pro"])
    weekly_limit = WEEKLY_LIMITS.get(plan, WEEKLY_LIMITS["pro"])

    now = datetime.now(JST)
    config = ensure_config()

    # Current 5-hour window usage (config-based)
    window_start, window_end = get_current_window_from_config(config, now)
    window_tokens = sum(r["total_tokens"] for r in records if window_start <= r["local_timestamp"] < window_end)
    window_pct = (window_tokens / window_limit) * 100 if window_limit > 0 else 0
    window_remaining = max(0, window_limit - window_tokens)

    # Time remaining in window
    time_remaining = window_end - now
    hours_left = int(time_remaining.total_seconds() // 3600)
    mins_left = int((time_remaining.total_seconds() % 3600) // 60)

    # Weekly usage (config-based)
    week_start, week_end = get_current_week_from_config(config, now)
    weekly_tokens = sum(r["total_tokens"] for r in records if week_start <= r["local_timestamp"] < week_end)
    weekly_pct = (weekly_tokens / weekly_limit) * 100 if weekly_limit > 0 else 0
    weekly_remaining = max(0, weekly_limit - weekly_tokens)

    # Colors
    def _color(pct):
        if pct >= 90:
            return "red"
        elif pct >= 70:
            return "yellow"
        return "green"

    def _bar(pct, width=25):
        filled = int(width * min(100, pct) / 100)
        c = _color(pct)
        return f"[{c}]{'█' * filled}[/{c}][dim]{'░' * (width - filled)}[/dim]"

    wc = _color(window_pct)
    wkc = _color(weekly_pct)

    panel = Panel(
        f"[bold]Plan:[/bold] {plan.upper()}    [dim]Window: {window_start.strftime('%H:%M')}~{window_end.strftime('%H:%M')} JST (残り {hours_left}h{mins_left}m)[/dim]\n"
        f"\n"
        f"[bold]⏱  5時間ウィンドウ:[/bold]\n"
        f"   {_bar(window_pct)} [{wc}]{window_pct:.1f}%[/{wc}]\n"
        f"   使用: {format_tokens(window_tokens)} / {format_tokens(window_limit)}    残り: [bold]{format_tokens(window_remaining)}[/bold]\n"
        f"\n"
        f"[bold]📅 今週 (月〜日):[/bold]\n"
        f"   {_bar(weekly_pct)} [{wkc}]{weekly_pct:.1f}%[/{wkc}]\n"
        f"   使用: {format_tokens(weekly_tokens)} / {format_tokens(weekly_limit)}    残り: [bold]{format_tokens(weekly_remaining)}[/bold]",
        title="[bold cyan]Token Limits[/bold cyan]",
        border_style="cyan",
        padding=(1, 2),
    )
    console.print(panel)


def _output_json(data):
    """Output data as JSON."""
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def main():
    parser = argparse.ArgumentParser(
        description="Claude Code Token Usage Reader - トークン使用量を可視化",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python token_reader.py                          # Daily report (default)
  python token_reader.py daily                    # Daily token usage
  python token_reader.py monthly                  # Monthly summary
  python token_reader.py session                  # Per-session usage
  python token_reader.py blocks                   # 5-hour billing windows
  python token_reader.py blocks --live            # Real-time dashboard
  python token_reader.py blocks --live --plan pro # Dashboard with Pro plan limit
  python token_reader.py daily --since 20250301 --until 20250331
  python token_reader.py daily --json             # JSON output
  python token_reader.py daily --breakdown        # Model breakdown
        """,
    )

    subparsers = parser.add_subparsers(dest="command")

    # Common arguments
    def add_common_args(p):
        p.add_argument("--since", help="Start date (YYYYMMDD)")
        p.add_argument("--until", help="End date (YYYYMMDD)")
        p.add_argument("--project", help="Filter by project name")
        p.add_argument("--json", action="store_true", help="Output as JSON")

    # Daily
    daily_parser = subparsers.add_parser("daily", help="Daily token usage report")
    add_common_args(daily_parser)
    daily_parser.add_argument("--breakdown", action="store_true", help="Show model breakdown")
    daily_parser.add_argument("--plan", choices=["pro", "max5", "max20"], default="pro", help="Plan type for limit display")

    # Monthly
    monthly_parser = subparsers.add_parser("monthly", help="Monthly token usage report")
    add_common_args(monthly_parser)
    monthly_parser.add_argument("--plan", choices=["pro", "max5", "max20"], default="pro", help="Plan type for limit display")

    # Session
    session_parser = subparsers.add_parser("session", help="Per-session token usage report")
    add_common_args(session_parser)

    # Blocks
    blocks_parser = subparsers.add_parser("blocks", help="5-hour billing window report")
    add_common_args(blocks_parser)
    blocks_parser.add_argument("--live", action="store_true", help="Real-time dashboard mode")
    blocks_parser.add_argument("--plan", choices=["pro", "max5", "max20"], default="pro", help="Plan type for limit display (default: pro)")

    # Monitor (shortcut for blocks --live)
    monitor_parser = subparsers.add_parser("monitor", help="Real-time usage monitor (shortcut for 'blocks --live')")
    monitor_parser.add_argument("--project", help="Filter by project name")
    monitor_parser.add_argument("--plan", choices=["pro", "max5", "max20"], default="pro", help="Plan type (default: pro)")

    # Init (set subscription start time)
    init_parser = subparsers.add_parser("init", help="Set subscription start time for accurate window calculation")
    init_parser.add_argument("--start", help="Subscription start date/time (e.g., '2026-03-13' or '2026-03-13 14:30')")
    init_parser.add_argument("--auto", action="store_true", help="Auto-detect from earliest log entry")
    init_parser.add_argument("--plan", choices=["free", "pro", "max5", "max20"], help="Set your plan type")

    # Plans (plan comparison and timetable)
    plans_parser = subparsers.add_parser("plans", help="Show plan comparison and 5-hour window timetable")

    args = parser.parse_args()

    if args.command is None:
        # Default to daily
        args.command = "daily"
        args.since = None
        args.until = None
        args.project = None
        args.json = False
        args.breakdown = False
        args.plan = "pro"

    commands = {
        "daily": cmd_daily,
        "monthly": cmd_monthly,
        "session": cmd_session,
        "blocks": cmd_blocks,
        "monitor": cmd_monitor,
        "init": cmd_init,
        "plans": cmd_plans,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
