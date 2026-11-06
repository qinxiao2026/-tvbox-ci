#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
refresh.py —— 自动重算 TVBox 配置（点播源 + 直播频道），产物写回仓库根：mycfg.json / live.txt
策略：
  - CORE 核心源永远保留；
  - 非核心源探测分三种：alive(活)/dead(明确判死)/unknown(超时未知)；
    保留条件 = alive，或 (unknown 且上次配置里就有) —— 绝不因单次超时误杀好源；
  - 新探测到的活源自动并入，之后粘住（抖动不再丢失）；
  - 直播拉到 0 频道时不覆盖 live.txt。
"""
import json, subprocess

UA = "Mozilla/5.0"
LIVE_URL = "https://gitee.com/qx_2026/mybox/raw/master/live.txt"
PRIOR_URL = "https://gitee.com/qx_2026/mybox/raw/master/mycfg.json"  # 读上一次结果做"粘滞"

# 核心稳定源：无条件保留
CORE = [
    ("lz",  "量子",  "https://cj.lziapi.com/api.php/provide/vod/"),
    ("ff",  "非凡",  "https://ffzy.tv/api.php/provide/vod/"),
    ("js",  "极速",  "https://jszyapi.com/api.php/provide/vod/"),
    ("bd",  "百度",  "https://api.apibdzy.com/api.php/provide/vod/"),
    ("360", "360",   "https://360zy.com/api.php/provide/vod/"),
]
# 额外候选：活则加入并粘住（想扩充源就把新地址加到这里）
EXTRA = [
    ("ff2", "非凡2", "https://api.ffzzyui.com/api.php/provide/vod/"),
    ("hs",  "华为",  "https://hwapi.vhomcas.com/api.php/provide/vod/"),
    ("tk",  "淘剧",  "https://taopjuy.com/api.php/provide/vod/"),
    ("bl",  "蓝鸟",  "https://api.lndbzy.com/api.php/provide/vod/"),
    ("sc",  "速成",  "https://dapaiapi.com/api.php/provide/vod/"),
]
LIVE_M3U = [
    "https://cdn.jsdelivr.net/gh/best-fan/iptv-sources@main/cn_cctv.m3u8",
    "https://cdn.jsdelivr.net/gh/best-fan/iptv-sources@main/cn_province.m3u8",
]


def curl(url, timeout=20):
    try:
        r = subprocess.run(["curl", "-sSL", "--max-time", str(timeout), "-A", UA, url],
                           capture_output=True, text=True, timeout=timeout + 8)
        return r.stdout or ""
    except Exception:
        return ""


def probe(api):
    """返回 'alive' / 'dead' / 'unknown'（超时/无响应=unknown，不下死结论）"""
    sep = "&" if "?" in api else "?"
    txt = curl(api + sep + "ac=detail&wd=%E5%BA%86%E4%BD%99%E5%B9%B4", 20)
    if not txt:
        return "unknown"
    low = txt.lower()
    if "closed" in low or "error code" in low:
        return "dead"
    try:
        j = json.loads(txt)
    except Exception:
        return "unknown"
    return "alive" if j.get("list") else "dead"


def site(key, name, api):
    return {"key": key, "name": name, "type": 1, "api": api,
            "searchable": 1, "quickSearch": 1, "filterable": 1}


def load_prior():
    """读上一次 Gitee 配置里的 sites，作为粘滞基线"""
    try:
        cfg = json.loads(curl(PRIOR_URL, 20))
    except Exception:
        return {}
    out = {}
    for s in cfg.get("sites", []):
        if s.get("api"):
            out[s["api"]] = s
    return out


def parse_m3u(text):
    res, name = [], None
    for ln in text.splitlines():
        if ln.startswith("#EXTINF"):
            name = ln.split(",")[-1].strip()
        elif ln.startswith("http") and name:
            res.append((name, ln.strip())); name = None
    return res


def main():
    prior = load_prior()
    core_apis = set(a for _, _, a in CORE)

    known = {}
    for k, n, a in CORE:
        known[a] = site(k, n, a)
    for k, n, a in EXTRA:
        known.setdefault(a, site(k, n, a))
    for a, s in prior.items():
        known.setdefault(a, s)

    sites = []
    for a, s in known.items():
        if a in core_apis:
            sites.append(s)
            continue
        st = probe(a)
        keep = (st == "alive") or (st == "unknown" and a in prior)
        if keep:
            sites.append(s)
        print("[%s] %-6s %s" % (st, ("keep" if keep else "drop"), s.get("name")))

    cfg = {"spider": "", "sites": sites, "parses": [],
           "lives": [{"name": "电视直播", "type": 0, "url": LIVE_URL, "playerType": 1, "epg": ""}],
           "wallpaper": ""}
    open("mycfg.json", "w", encoding="utf-8").write(json.dumps(cfg, ensure_ascii=False, indent=2))

    buckets = {"央视": [], "卫视": []}
    for url in LIVE_M3U:
        for name, u in parse_m3u(curl(url, 30)):
            b = "央视" if "CCTV" in name.upper() else "卫视"
            if any(n == name for n, _ in buckets[b]):
                continue
            buckets[b].append((name, u))
    total = len(buckets["央视"]) + len(buckets["卫视"])
    if total == 0:
        print("[live] 拉取到 0 个频道，跳过覆盖 live.txt")
    else:
        lines = []
        for b in ["央视", "卫视"]:
            lines.append("%s,#genre#" % b)
            lines += ["%s,%s" % (n, u) for n, u in buckets[b]]
        open("live.txt", "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("done: vod=%d live_cctv=%d live_sat=%d" % (len(sites), len(buckets["央视"]), len(buckets["卫视"])))


if __name__ == "__main__":
    main()
