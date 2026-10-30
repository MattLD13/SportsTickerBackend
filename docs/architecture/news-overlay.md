# News overlays

News is a durable overlay. It shares the panel with the active base mode. It never replaces the base strip or resets its scroll state.

`sports_ticker/application/events.py` owns event persistence and delivery. `sports_ticker/projections/data_api.py` projects pending events for one ticker. `ticker_core/ui/news_banner.py` draws the overlay.

Create an event through the operator route:

```text
POST /news
```

The route validates the payload and delivers it only to the tickers in `ticker_ids`. The controller app can dismiss one overlay with `POST /tickers/<id>/events/<event_id>/ack`.

News rendering uses the active mode as the base frame. A score alert has higher display priority. Both overlay types preserve the current content strip and scroll phase.
