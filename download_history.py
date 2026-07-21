#!/usr/bin/env python3
"""下载自选股（UNIVERSE）过去5年的日线数据，保存为 CSV，供后续算法建模使用。
数据源：Massive/Polygon v2/aggs（复权日线，与 index.html 口径一致）。
"""
import csv
import re
import sys
import time
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).parent
CONFIG_JS = ROOT / "config.js"
OUT_DIR = ROOT / "historical_data"
BASE = "https://api.polygon.io"

# 与 index.html 的 UNIVERSE 保持一致
TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
    "MCD", "TSM", "JPM", "CEG", "AVGO", "BRK.B", "LEU", "LLY",
    "QQQ", "SPY",
]


def load_api_key() -> str:
    text = CONFIG_JS.read_text(encoding="utf-8")
    m = re.search(r'MASSIVE_API_KEY\s*=\s*"([^"]+)"', text)
    if not m:
        raise RuntimeError(f"未能在 {CONFIG_JS} 中找到 MASSIVE_API_KEY")
    return m.group(1)


def fetch_daily_bars(ticker: str, api_key: str, start: str, end: str) -> list[dict]:
    """分页抓取某标的的日线数据，返回按时间升序的 bar 列表。"""
    bars: list[dict] = []
    url = f"{BASE}/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}"
    params = {"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": api_key}

    while url:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") not in ("OK", "DELAYED") and not data.get("results"):
            raise RuntimeError(f"{ticker}: API 返回异常: {data}")
        bars.extend(data.get("results", []))

        next_url = data.get("next_url")
        if next_url:
            url = next_url
            params = {"apiKey": api_key}  # next_url 已带其余参数
        else:
            url = None
    return bars


def write_csv(ticker: str, bars: list[dict]) -> Path:
    safe_name = ticker.replace(".", "-")  # BRK.B -> BRK-B，避免文件名歧义
    out_path = OUT_DIR / f"{safe_name}.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "open", "high", "low", "close", "volume", "vwap", "transactions"])
        for bar in bars:
            d = date.fromtimestamp(bar["t"] / 1000).isoformat()
            writer.writerow([
                d,
                bar.get("o"), bar.get("h"), bar.get("l"), bar.get("c"),
                bar.get("v"), bar.get("vw"), bar.get("n"),
            ])
    return out_path


def main():
    api_key = load_api_key()
    end = date.today()
    start = end.replace(year=end.year - 5)
    start_s, end_s = start.isoformat(), end.isoformat()

    OUT_DIR.mkdir(exist_ok=True)
    print(f"下载区间: {start_s} ~ {end_s}\n输出目录: {OUT_DIR}\n")

    failed = []
    for ticker in TICKERS:
        try:
            bars = fetch_daily_bars(ticker, api_key, start_s, end_s)
            if not bars:
                print(f"[跳过] {ticker}: 无数据")
                failed.append(ticker)
                continue
            path = write_csv(ticker, bars)
            print(f"[完成] {ticker}: {len(bars)} 条 -> {path.name}")
        except Exception as e:
            print(f"[失败] {ticker}: {e}")
            failed.append(ticker)
        time.sleep(0.1)

    print("\n全部完成。" if not failed else f"\n完成，但以下标的失败/无数据: {failed}")


if __name__ == "__main__":
    sys.exit(main())
