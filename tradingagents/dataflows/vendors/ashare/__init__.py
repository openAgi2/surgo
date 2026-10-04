"""A-share (China) market data: daily OHLCV via sina/tencent/baostock/tushare.

A clean-room vendor for mainland Chinese equities. It borrows *behavior* (which
upstream endpoints serve A-share daily bars, their column shapes, and the
fallback order) from TradingAgents-CN's Apache-2.0 ``tradingagents/`` engine,
but the implementation here is written from scratch against the surgo vendor
contract — no code is copied, and nothing depends on TradingAgents-CN's
proprietary ``app/`` / ``core/`` layers.
"""
