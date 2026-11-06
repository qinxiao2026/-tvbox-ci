#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
refresh.py —— 自动重算 TVBox 配置，产物写回仓库根：mycfg.json / live.txt / backup_configs.txt
数据源：
  1) 自有 CORE 稳定源（永远保留）；
  2) 上次 Gitee 配置（粘滞基线，防超时误删）；
  3) Awesome Zhuiju Free 仓库（大佬每日维护+测活的 TVBox 配置清单）：
     - resources/resources.json  -> category=tvbox_config 的配置地址
     - reports/availability.json -> 每个地址的存活状态
     从中抽取 type:1 的普通采集站点合并进来（不碰需要 jar 的），多仓递归一层。
探测三态：alive / dead(明确) / unknown(超时)，unknown 不下死结论。
直播拉到 0 频道不覆盖 live.txt。
"""
import json, subprocess, urllib.parse

UA = "Mozilla/5.0"
LIVE_URL = "https://gitee.com/qx_2026/mybox/raw/master/live.txt"
PRIOR_URL = "https://gitee.com/qx_2026/mybox/raw/master/mycfg.json"
AZ = "https://raw.githubusercontent.com/laoma528/awesome-zhuiju-free/main"
RES_URL = AZ + "/resources/resources.json"
AVAIL_URL = AZ + "/reports/availability.json"

MAX_SITES = 150  # 合并后站点上限，防膨胀

CORE = [
    ("lz",  "量子",  "https://cj.lziapi.com/api.php/provide/vod/"),
    ("ff",  "非凡",  "https://ffzy.tv/api.php/provide/vod/"),
    ("js",  "极速",  "https://jszyapi.com/api.php/provide/vod/"),
    ("bd",  "百度",  "https://api.apibdzy.com/api.php/provide/vod/"),
    ("360", "360",   "https://360zy.com/api.php/provide/vod/"),
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


def idn(url):
    """中文域名转 punycode，便于 curl 访问"""
    try:
        p = urllib.parse.urlsplit(url)
        host = p.netloc
        if any(ord(c) > 127 for c in host):
            host = host.encode("idna").decode()
            return urllib.parse.urlunsplit((p.scheme, host, p.path, p.query, p.fragment))
    except Exception:
        pass
    return url


def fetch_json(url, timeout=20):
    txt = curl(idn(url), timeout)
    try:
        return json.loads(txt)
    except Exception:
        return None


def probe(api):
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


def mk_site(name, api):
    return {"key": "", "name": name or "", "type": 1, "api": api,
            "searchable": 1, "quickSearch": 1, "filterable": 1}


def extract_sites(cfg, depth=0):
    """从一份 TVBox 配置里抽取 type:1 且有 http api 的普通采集站点；多仓递归一层"""
    out = []
    if not isinstance(cfg, dict):
        return out
    for s in cfg.get("sites", []):
        if isinstance(s, dict) and s.get("type") == 1 and str(s.get("api", "")).startswith("http"):
            out.append(mk_site(s.get("name"), s.get("api")))
    if depth < 1:
        subs = cfg.get("urls") or cfg.get("houses") or []
        for u in subs:
            sub = (u.get("url") or u.get("api")) if isinstance(u, dict) else None
            if sub and str(sub).startswith("http"):
                out += extract_sites(fetch_json(sub, 15), depth + 1)
    return out


def load_prior():
    cfg = fetch_json(PRIOR_URL)
    out = {}
    if isinstance(cfg, dict):
        for s in cfg.get("sites", []):
            if s.get("api"):
                out[s["api"]] = s
    return out


def load_az_configs():
    """返回 [(name, url)] 取 category==tvbox_config；以及 {url: status} 测活表"""
    res = fetch_json(RES_URL)
    configs = []
    if isinstance(res, dict):
        for r in res.get("resources", []):
            if r.get("category") == "tvbox_config" and r.get("url"):
                configs.append((r.get("name") or r.get("id"), r["url"]))
    avail = {}
    av = fetch_json(AVAIL_URL)
    if isinstance(av, dict):
        for r in av.get("results", []):
            avail[r.get("url")] = r.get("status")
    return configs, avail


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

    sites, apis = [], set()

    def add(name, api):
        if api and api not in apis:
            apis.add(api)
            sites.append(mk_site(name, api))

    # 1) 核心源
    for k, n, a in CORE:
        add(n, a)

    # 2) 从大佬存活配置吸收采集站点
    configs, avail = load_az_configs()
    harvested = 0
    for name, url in configs:
        st = avail.get(url, "unknown")
        if st in ("unreachable", "error"):
            print("[skip dead] %-8s %s" % (name, url))
            continue
        cfg = fetch_json(url)
        got = extract_sites(cfg, 0)
        if not got:
            print("[cfg empty] %-8s %s" % (name, url))
            continue
        for s in got:
            if s["api"] not in apis:
                apis.add(s["api"]); sites.append(s); harvested += 1
        print("[cfg alive] %-8s +%d  (az=%s)" % (name, len(got), st))
    print("harvested from zhuiju: %d" % harvested)

    # 3) 粘滞：上次配置里的站点继续保留
    for a, s in prior.items():
        if a not in apis:
            apis.add(a)
            sites.append(mk_site(s.get("name"), a))

    # 4) 去重后重排 key，封顶
    sites = sites[:MAX_SITES]
    for i, s in enumerate(sites):
        s["key"] = "s%03d" % i

    cfg = {"spider": "", "sites": sites, "parses": [],
           "lives": [{"name": "电视直播", "type": 0, "url": LIVE_URL, "playerType": 1, "epg": ""}],
           "wallpaper": ""}
    open("mycfg.json", "w", encoding="utf-8").write(json.dumps(cfg, ensure_ascii=False, indent=2))
    print("total vod sites: %d (core=%d)" % (len(sites), len(core_apis)))

    # 5) 备用清单：大佬维护的 TVBox 配置地址 + 测活状态
    lines = ["# 大佬维护的 TVBox 配置地址（Awesome Zhuiju Free），每日同步，状态来自其测活报告",
             "# 可整行复制到影视仓/TVBox 手动切换备用"]
    for name, url in configs:
        lines.append("%-10s | %-10s | %s" % (avail.get(url, "unknown"), name, url))
    open("backup_configs.txt", "w", encoding="utf-8").write("\n".join(lines) + "\n")

    # 6) 直播
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
        out = []
        for b in ["央视", "卫视"]:
            out.append("%s,#genre#" % b)
            out += ["%s,%s" % (n, u) for n, u in buckets[b]]
        open("live.txt", "w", encoding="utf-8").write("\n".join(out) + "\n")
    print("done: live_cctv=%d live_sat=%d" % (len(buckets["央视"]), len(buckets["卫视"])))


if __name__ == "__main__":
    main()
