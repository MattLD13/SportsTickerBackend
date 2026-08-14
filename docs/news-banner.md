# News overlays

News is a durable V2 overlay. It shares the panel with the active base mode. It never replaces the base strip or resets its scroll state.

`sports_ticker/application/events.py` owns event persistence and delivery. `sports_ticker/projections/data_api.py` projects pending events for one ticker. `ticker_core/features/alerts/news_banner_port.py` draws the overlay.

Create an event through the V2 API:

```text
POST /api/v2/events/news
```

The route validates the payload and delivers it only to its target tickers. The Pi acknowledges delivery through the ticker event acknowledgement route.

News rendering uses the active mode as the base frame. A score alert has higher display priority. Both overlay types preserve the current content strip and scroll phase.
