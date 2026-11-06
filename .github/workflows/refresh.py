#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
refresh.py —— Gitee Go 每天自动重算 TVBox 配置（点播存活源 + 直播频道）
产物写回仓库根目录：mycfg.json / live.txt，由流水线 commit 回去。
"""
import json, subprocess

UA = "Mozilla/5.0"
# 直播清单地址：指向本仓库 Gitee raw 的 live.txt
LIVE_URL = "https://gitee.com/qx_2026/mybox/raw/master/live.txt"

VOD_CANDIDATES = [
    ("lz",  "量子",  "https://cj.lziapi.com/api.php/provide/vod/"),
    ("ff",  "非凡",  "https://ffzy.tv/api.php/provide/vod/"),
    ("ff2", "非凡2", "https://api.ffzzyui.com/api.php/provide/vod/"),
    ("js",  "极速",  "https://jszyapi.com/api.php/provide/vod/"),
    ("bd",  "百度",  "https://api.apibdzy.com/api.php/provide/vod/"),
    ("360", "360",   "https://360zy.com/api.php/provide/vod/"),
    ("hs",  "华为",  "https://hwapi.vhomcas.com/api.php/provide/vod/"),
    ("tk",  "淘剧",  "https://taopjuy.com/api.php/provide/vod/"),
    ("bl",  "蓝鸟",  "https://api.lndbzy.com/api.php/provide/vod/"),
    ("sc",  "速成",  "https://dapaiapi.com/api.php/provide/vod/"),
]
LIVE_M3U = [
    "https://cdn.jsdelivr.net/gh/best-fan/iptv-sources@main/cn_cctv.m3u8",
    "https://cdn.jsdelivr.net/gh/best-fan/iptv-sources@main/cn_province.m3u8",
]


def curl(url, timeout=15):
    try:
        r = subprocess.run(["curl", "-sSL", "--max-time", str(timeout), "-A", UA, url],
                           capture_output=True, text=True, timeout=timeout + 8)
        return r.stdout or ""
    except Exception:
        return ""


def vod_alive(api):
    sep = "&" if "?" in api else "?"
    txt = curl(api + sep + "ac=detail&wd=%E5%BA%86%E4%BD%99%E5%B9%B4", 12)
    if not txt:
        return False
    low = txt.lower()
    if "closed" in low or "error code" in low:
        return False
    try:
        return bool(json.loads(txt).get("list"))
    except Exception:
        return False


def parse_m3u(text):
    out, name = [], None
    for ln in text.splitlines():
        if ln.startswith("#EXTINF"):
            name = ln.split(",")[-1].strip()
        elif ln.startswith("http") and name:
            out.append((name, ln.strip())); name = None
    return out


def main():
    sites = []
    for key, name, api in VOD_CANDIDATES:
        if vod_alive(api):
            sites.append({"key": key, "name": name, "type": 1, "api": api,
                          "searchable": 1, "quickSearch": 1, "filterable": 1})
            print("[vod alive]", name)
        else:
            print("[vod dead ]", name)

    cfg = {"spider": "", "sites": sites, "parses": [],
           "lives": [{"name": "电视直播", "type": 0, "url": LIVE_URL, "playerType": 1, "epg": ""}],
           "wallpaper": ""}
    open("mycfg.json", "w", encoding="utf-8").write(json.dumps(cfg, ensure_ascii=False, indent=2))

    buckets = {"央视": [], "卫视": []}
    for url in LIVE_M3U:
        for name, u in parse_m3u(curl(url, 25)):
            b = "央视" if "CCTV" in name.upper() else "卫视"
            if any(n == name for n, _ in buckets[b]):
                continue
            buckets[b].append((name, u))
    lines = []
    for b in ["央视", "卫视"]:
        lines.append("%s,#genre#" % b)
        lines += ["%s,%s" % (n, u) for n, u in buckets[b]]
    open("live.txt", "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("done: vod=%d live_cctv=%d live_sat=%d" % (len(sites), len(buckets["央视"]), len(buckets["卫视"])))


if __name__ == "__main__":
    main()
