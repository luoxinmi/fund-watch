# fund-watch

ADL 四层模型（liq-heatmap 图 16）的基金历史采样，**私有**。

- 每小时采样：币安保险基金（按币所在组）、OI、价格、Gate 全站保险基金
- 数据：`data/fund/YYYYMM.jsonl`，每月一个文件
- 关键：GitHub runner 直连 `fapi.binance.com` 会 451，这里用 `www.binance.com/fapi/...` 透传（实测 200）

消费方：本机 `liq-heatmap/scripts/fund_history.py --from-github`。
