"""Dated, reviewed observation universe; never an automatic promotion/risk change.

CoinGecko market-cap snapshot was checked against Binance public Spot USDT
TRADING symbols. Stablecoins and duplicate exposures are excluded. Higher-ranked
FIGR_HELOC and XMR had no eligible Binance Spot pair. This list is deliberately
fixed for reproducible forward evidence; it does not claim a permanent live rank.
"""

DEFAULT_SYMBOLS = (
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT",
    "TRXUSDT", "ZECUSDT", "HYPEUSDT", "DOGEUSDT", "LINKUSDT",
)

UNIVERSE_METADATA = {
    "selection": "10 mayores por capitalización con par Spot USDT activo en Binance; sin stablecoins ni duplicados. Selección fijada y fechada.",
    "selected_at": "2026-10-16T14:42:58Z",
    "source": "https://www.coingecko.com/",
}
