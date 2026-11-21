#!/usr/bin/env python3
"""币安保险基金分层采样（fund-watch 仓库，多档质数间隔）。

为什么用 www.binance.com
------------------------
GitHub Actions runner 在美国，直连 `fapi.binance.com` 返回 **451**；
`www.binance.com/fapi/<path>` 是网页端透传，实测 **200 且返回真实 JSON**。

分层档位（cron-job.org 每档一个 job；与 monitor 的 60 分钟时序错开，取质数/非整除间隔）
--------------------------------------------------------------------------------
| bucket | 触发 | 写什么 |
|---|---|---|
| `3m` / `5m` / `7m` | 分钟内按档 | focus：全站合计 + 关注币（EVAA/ETH/PEPE/BONK）所在组 |
| `13m` / `23m` / `37m` / `47m` | 同上 | groups：全站合计 + 124 组全量 |
| `101m` | 每小时 :41 + `--min-gap 6060` | assets：全站 + 124 组 + 分资产（USDT/USDC/其他） |

输出：`data/fund/<bucket>_YYYYMM.jsonl`，每行带 `kind`：
  `total`（全站合计）· `coin`（关注币组）· `group`（单个组）· `asset`（组的分资产）
旧的 `data/fund/YYYYMM.jsonl`（5 分钟旧格式）保留不动，历史数据别删。

`--min-gap 秒`：距该档上次采样不足就跳过并以 0 退出（101m 档用「每小时触发 + 6060 秒节流」
实现严格 101 分钟间隔——cron 表达不了跨小时的质数间隔）。
"""
import argparse
import json
import os
import time
import urllib.request

BASE = "https://www.binance.com"
FOCUS = ("EVAA", "ETH", "PEPE", "BONK")
SCOPE = {"3m": "focus", "5m": "focus", "7m": "focus",
         "13m": "groups", "23m": "groups", "37m": "groups", "47m": "groups",
         "101m": "assets"}


def _get(path, timeout=20):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "Mozilla/5.0 Chrome/126"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def find_group(ins, sym):
    want = {f"{sym}USDT", f"{sym}USDC"}
    for p in ("100", "1000", "10000", "100000", "1000000"):
        want.add(f"{p}{sym}USDT")
        want.add(f"{p}{sym}USDC")
    return next((g for g in ins if any(x in want for x in (g.get("symbols") or []))), None)


def group_fund(grp):
    """组内 USDT+USDC 合计（稳定币才可直接相加；实物 BTC/BNB 另记数量）。"""
    usdt = usdc = 0.0
    other = 0
    for x in grp.get("assets") or []:
        a = str(x.get("asset", "")).upper()
        v = float(x.get("marginBalance") or 0)
        if a == "USDT":
            usdt += v
        elif a == "USDC":
            usdc += v
        else:
            other += 1
    return usdt, usdc, other


def gate_insurance():
    try:
        req = urllib.request.Request("https://api.gateio.ws/api/v4/futures/usdt/insurance",
                                     headers={"User-Agent": "fund-watch"})
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read().decode())
        return float(d[-1]["b"]) if d else None
    except Exception:
        return None


def last_ts(path):
    """从文件尾部读最后一行的 ts（文件可能几 MB，不整读）。"""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            if size == 0:
                return None
            f.seek(max(0, size - 4096))
            tail = f.read().decode("utf-8", "ignore").strip().splitlines()
            for line in reversed(tail):
                try:
                    return int(json.loads(line).get("ts") or 0) or None
                except Exception:
                    continue
    except Exception:
        return None
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", default="5m", choices=sorted(SCOPE))
    ap.add_argument("--out", default="data/fund")
    ap.add_argument("--min-gap", type=int, default=0, help="秒；距上次采样不足则跳过")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    ts = int(time.time())
    path = os.path.join(a.out, f"{a.bucket}_{time.strftime('%Y%m', time.gmtime(ts))}.jsonl")
    if a.min_gap:
        prev = last_ts(path)
        if prev and ts - prev < a.min_gap:
            print(f"skip：距上次 {ts - prev}s < min-gap {a.min_gap}s")
            return 0

    try:
        ins = _get("/fapi/v1/insuranceBalance?limit=200")
    except Exception as e:
        print("insuranceBalance 失败:", e)
        return 1
    gate = gate_insurance()
    scope = SCOPE[a.bucket]
    rows = []
    total_usdt = total_usdc = 0.0
    for g in ins:
        u, c, _o = group_fund(g)
        total_usdt += u
        total_usdc += c
    rows.append({"ts": ts, "bucket": a.bucket, "kind": "total",
                 "usdt": round(total_usdt, 2), "usdc": round(total_usdc, 2),
                 "groups": len(ins), "gate_insurance": gate})

    if scope == "focus":
        for sym in FOCUS:
            grp = find_group(ins, sym)
            if not grp:
                continue
            u, c, o = group_fund(grp)
            oi = price = None
            try:
                oi = float(_get(f"/fapi/v1/openInterest?symbol={sym}USDT")["openInterest"])
                price = float(_get(f"/fapi/v1/ticker/price?symbol={sym}USDT")["price"])
            except Exception:
                pass
            rows.append({"ts": ts, "bucket": a.bucket, "kind": "coin", "sym": sym,
                         "group_fund": round(u + c, 2), "group_syms": grp.get("symbols"),
                         "oi": oi, "price": price})
    else:
        # groups / assets：124 组全量（gid 用序号，与 monitor 的 gxxx 对齐规则一致）
        for i, grp in enumerate(ins):
            u, c, o = group_fund(grp)
            row = {"ts": ts, "bucket": a.bucket, "kind": "group", "gid": f"g{i:03d}",
                   "fund": round(u + c, 2), "n": len(grp.get("symbols") or [])}
            if scope == "assets":
                row.update({"usdt": round(u, 2), "usdc": round(c, 2),
                            "other_assets": o})
            rows.append(row)

    with open(path, "a") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"{a.bucket} [{scope}] 写入 {path} {len(rows)} 行 · "
          f"全站 ${(total_usdt + total_usdc)/1e6:.2f}M · Gate ${(gate or 0)/1e6:.2f}M")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
