# fund-watch

ADL 四层模型（liq-heatmap 图 16）的基金历史采样，**Public**。

- 每 5 分钟采样（cron `2-57/5 * * * *`，避开整点拥堵）：币安保险基金（按币所在组）、OI、价格、Gate 全站保险基金
- 采样币种：`EVAA,ETH,PEPE,BONK`（在 `.github/workflows/fund.yml` 的 `--symbols` 里改）
- 数据：`data/fund/YYYYMM.jsonl`，每月一个文件
- 关键：GitHub runner 直连 `fapi.binance.com` 会 451，这里用 `www.binance.com/fapi/...` 透传（实测 200）

消费方：本机 `liq-heatmap/scripts/fund_history.py --from-github`（5 分钟采样，合并去重后写本地 jsonl）。

注意：`monitor` 仓库里也有 `data/fund/`，那是**组基金时序**（`groups_YYYYMM.jsonl`，每小时一行/组），
与本仓库的 5 分钟采样不是一回事。
