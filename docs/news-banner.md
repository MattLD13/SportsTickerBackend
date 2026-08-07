# News Banner

A half-width banner for breaking news. It is not the score alert.

## What it is

A score alert takes the whole panel, because a score is the thing you turned the
board on for. News is not that. The banner takes the left 192 pixels and lets the
strip keep scrolling in the right 192, so a trade never costs you the scores.

Each kind of news stays in its own mode:

| Mode | Domain | What appears |
|---|---|---|
| sports, live, my_teams, sports_full, soccer_full | `sports` | Trades and signings for a followed club |
| stocks | `stocks` | Company and market headlines |

A trade never appears over the market scroll. A market headline never appears
over the scores. There is no banner for a price move on its own.

## The layout

A trade shows both clubs in the header, drawn in their own colours with an arrow
between them, over two lines of detail:

```
[TRADE]  TB --> STL
RHP RYAN HELSLEY FOR TWO PROSPECTS
```

Stock news shows the symbol and the day's move in the header, over three lines
of headline. Three, because real headlines run to a median of 65 characters and
a maximum of 89, and two lines of 35 cut a quarter of them.

Both use the 6-pixel font at 35 characters per line. Text that runs past the
last line is cut with a full stop. It is never dropped in silence.

## What is built

| Piece | File | State |
|---|---|---|
| Item store | `sports_ticker/services/news_alerts.py` | Done |
| MLB trades and signings | `sports_ticker/fetchers/transactions.py` | Done |
| Poll loop, every 10 minutes | `transactions_worker` in `sports_ticker/workers.py` | Done |
| Push route | `sports_ticker/routes/news.py` | Done |
| Delivery through `/data` | `_news_for_ticker` in `sports_ticker/routes/state.py` | Done |
| Banner drawing on the panel | `tools/render_news_banner_concepts.py` | **Concept only** |

The controller does not draw the banner yet. The concept renderer produces the
artwork, and it has to be moved into `ticker_controller/modes/` and driven from
`render_loop` before anything reaches a panel.

## Adding an item by hand

```bash
curl -X POST http://<backend>:5000/api/news -H 'Content-Type: application/json' -d '{
  "kind": "TRADE", "sport": "nhl", "from": "VAN", "to": "NYR",
  "text": "J.T. Miller for Kakko, a 2027 first and a conditional third"
}'
```

Fields: `kind` (TRADE, SIGNS, NEWS), `text`, `sport`, `from`, `to`, `domain`
(`sports` or `stocks`), and `symbol` for a stocks item. Colours are resolved
from the ticker's own team lookup, so a caller sends only abbreviations.

The response lists which tickers follow a club in the item, so a board that
stays blank explains itself.

`GET /api/news` lists what is currently held.

## League coverage

This is the part that decides what can ever be automatic.

| League | Source | Player | Both clubs | State |
|---|---|---|---|---|
| MLB | `statsapi.mlb.com/api/v1/transactions` | yes | yes | **Built** |
| NFL | ESPN core API | in the sentence only | no | Needs work, see below |
| NHL | none found | — | — | Blocked |
| NBA | none found | — | — | Blocked |

### MLB, which is built

The league publishes its own feed, free and without a key. It gives `typeDesc`,
`person`, `fromTeam`, `toTeam`, `date`, and a full sentence. Nothing has to be
read out of English.

Two things the feed does that the fetcher has to correct:

1. **One trade arrives as many rows**, one per player moved. The Tigers and
   Padres deal arrives four times. Rows are grouped by their description, which
   is identical across a deal.
2. **The rows run both ways.** Mize leaves Detroit on one row and Mayfield
   arrives on another. Direction cannot be taken from row order, so the acting
   club is parsed from the start of the sentence instead. Get this wrong and the
   arrow points against the detail printed under it.

### NFL, which needs work

ESPN carries transactions, but only for the NFL, and the path needs a season:

    http://sports.core.api.espn.com/v2/sports/football/leagues/nfl/seasons/2025/transactions

Each item holds `date`, `description`, and one `team` reference. There is no
player field and no counterparty. So the banner can show `--> NYG` and a
sentence, but not `TB --> NYG`.

**To build it:** decide whether one club is enough. If it is, the work is small:
resolve the `$ref` to a team, and reuse the MLB grouping. If both clubs are
needed, the second club has to be read out of the sentence, which is guesswork
and the reason this is not built.

### NHL and NBA, which are blocked

Neither league publishes a transactions endpoint. For the NHL I probed seven
paths across `api-web.nhle.com`, `api.nhle.com`, and `records.nhl.com`. All
returned 404 while three endpoints the app already uses answered normally at the
same moment, so the requests were sound and the paths simply do not exist.

**To build either one, something has to supply the data:**

1. **A paid provider.** Sportradar and Stats Perform both carry transactions for
   all four leagues, with the clubs as fields. This is the only route that gives
   full automation.
2. **A site that publishes structured moves**, such as PuckPedia or Spotrac.
   Neither offers a documented free API, so this means scraping, which breaks
   without warning.
3. **The push route.** Already built, and it covers both leagues today.

**Do not keyword-match news headlines.** ESPN's news feed is the only other
thing on offer, and using it means reading English to decide what happened. The
score describer already carries the scar from that approach: it looked for
"pick" in a play description, and every touchdown pass thrown by Kenny Pickett
became a PICK SIX.

## Re-check in October

The NHL and NBA seasons are out while this was written. The 404s are not
seasonal, because a missing path stays missing. ESPN covering only the NFL is
also proven rather than assumed: MLB is in season with confirmed trades and its
ESPN transaction count is still zero.

Even so, both are worth re-testing once the seasons start. A feed that is quiet
in the off-season is not proof that it stays quiet.
