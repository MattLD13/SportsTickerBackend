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
| NFL trades | `sports_ticker/fetchers/transactions.py` | Done |
| NHL trades | `sports_ticker/fetchers/transactions.py` | Done |
| NBA trades | `sports_ticker/fetchers/transactions.py` | Done |
| Stock headlines | `sports_ticker/fetchers/stock_news.py` | Done |
| Poll loop, every 10 minutes | `news_worker` in `sports_ticker/workers.py` | Done |
| Push route | `sports_ticker/routes/news.py` | Done |
| Delivery through `/data` | `_news_for_ticker` in `sports_ticker/routes/state.py` | Done |
| Banner drawing on the panel | `ticker_controller/modes/news_banner.py` | Done |

The banner rides on the scroll rather than replacing it. A score alert freezes
the strip and blocks the render loop; this is applied to each ordinary scroll
frame instead, so the strip keeps moving in the half beside it and the scroll
cadence is untouched.

Render previews with `python tools
ender_news_banner.py`.

## Test pages

* `/debug/news` pushes a banner with a button, one preset per league.
* `/debug/alerts` does the same for the full-screen score alert.

Both are served by the backend, so they call the API on the same origin and
need no key. Both report whether the selected ticker will show the item.

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

A pushed item gets a fresh id every time, so the same banner can be sent again
and again. A fetched item keeps a stable id instead, so a feed cannot re-emit
one trade on every poll.

## Stock news

Two sources, chosen by whether a Finnhub key is set.

* **Finnhub** is the primary. The quote fetcher already runs on those keys, and
  its company-news endpoint is filtered by symbol at the source.
* **Yahoo RSS** is the fallback and needs no key, which matches the way the
  quote fetcher drops into simulation mode without one.

The fallback needs filtering that Finnhub does not. Yahoo's per-symbol feed is
sector-wide: a query for NVDA returns Cloudflare and Calumet headlines, and only
about a third of the feed names the company.

Naming a company is not the same as being about it. "AEye to Participate in
J.P. Morgan Auto Conference" names the bank and is about AEye. Two layers sort
that out, and the second is optional.

1. **A word rule.** The company must appear in the first four words, where a
   subject sits. Free and instant, and it drops the AEye headline. It also
   drops a few good ones, such as "Tim Cook Says There's No Better Person to
   Take Over at Apple", where the company arrives last.
2. **A model**, which reads the shortlist and answers properly. It recovers the
   ones the rule loses. One request per poll, all candidates batched.

Company names come from Yahoo's search endpoint, cached for a day, with the
generic half dropped so "corporation" does not match everything.

### The model layer

Off by default. Set a key and it turns on:

    HEADLINE_AI_KEY=...        # or GROQ_API_KEY
    HEADLINE_AI_URL=...        # default: Groq
    HEADLINE_AI_MODEL=...      # default: llama-3.1-8b-instant

Any OpenAI-compatible endpoint works, so the provider is a matter of which key
is set. Groq is the default because its free tier needs no credit card and
allows 14,400 requests a day, against the one request per poll this makes.
Cerebras and OpenRouter speak the same protocol; point the URL and model at
either and nothing else changes.

Finnhub filters by symbol at the source, so the model runs only on the keyless
path. When no model key is set, or the call fails for any reason, the word rule
stands. A model that is down costs relevance, never the whole feed.

One headline per symbol per poll, freshest first, six in total. The feed carries
twenty per symbol and a board showing all of them would be a news ticker rather
than a stock ticker.

Symbols come from the stock sectors that are switched on. The day's move comes
from the quote cache the stocks worker already keeps, so this adds no price
request.

## League coverage

This is the part that decides what can ever be automatic.

| League | Source | Player | Both clubs | State |
|---|---|---|---|---|
| MLB | `statsapi.mlb.com/api/v1/transactions` | yes | yes | **Built** |
| NFL | ESPN core API | in the sentence | by name lookup | **Built** |
| NHL | NHL forge content API | in the headline | by name lookup | **Built** |
| NBA | `stats.nba.com` player movement | yes | receiving club is data | **Built** |

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

### NFL, which is built

ESPN carries transactions, but only for the NFL, and the path needs a season:

    http://sports.core.api.espn.com/v2/sports/football/leagues/nfl/seasons/2025/transactions

Each item holds `date`, `description`, and one `team` reference. The acting club
is data. Everything else is English.

The other club is read out of the sentence, and that is safe here only because
club names are a closed set of 32. Matching "Philadelphia" or "the Pittsburgh
Steelers" against a known list is a lookup. It is not the same as guessing at a
word, which is what turned every Kenny Pickett touchdown pass into a PICK SIX.

Four things the feed does that the fetcher corrects:

1. **Both clubs file the same trade.** One reads "Traded X to Y" and the other
   "Received X from a trade with Y". Only the sending side is kept, or the same
   deal is drawn twice, once backwards.
2. **Unrelated moves share a field.** "Traded S Kyle Dugger to the Pittsburgh
   Steelers. Signed S John Saunders Jr. to the active roster." Only the first
   sentence is the trade.
3. **Rows are newest first,** so one page covers about seven weeks. Anything
   older than two days is dropped, or the first run after a restart puts a whole
   season of trades on the panel at once.
4. **Trades are rare.** A full season carried 5, against 1276 transactions. The
   rest are signings and releases, which are roster churn rather than news.

### NHL, which is built

The league publishes no transaction feed, but it does publish its stories, and
it tags them itself:

    https://forge-dapi.d3.nhle.com/v2/content/en-us/stories?tags.slug=transactions

A story carries a `transactions` tag and a `teamid-N` tag. The tag is the
authority on what the story is about, so nothing has to decide from prose
whether a move happened. Only the two clubs and the direction are read from the
headline, and both are closed sets: the club is one of 32, the verb is one of
two.

Three headline forms cover the league. NHL.com writes "Schmid traded to Panthers
by Golden Knights". A club writes "Canadiens acquire Pastujov from the Anaheim
Ducks" or "Canadiens trade Gallagher to the Vancouver Canucks".

Across 1200 tagged stories this resolves 84 percent of trade headlines. The rest
are skipped. That is the safe direction: a headline it cannot read costs a
missed banner, never a wrong one.

Three traps:

1. **The stats endpoint lists 62 franchises**, including clubs folded a century
   ago. Unfiltered, "Toronto" matches the 1918 Arenas and a Maple Leafs trade is
   drawn as TAN. Only the 32 in the current standings count.
2. **`requests` breaks the pagination.** The API takes `$limit` and `$skip`, and
   requests percent-encodes the dollar sign, which the server ignores. Every
   page then returns the same default 25 rows. The URL is built by hand.
3. **Both clubs publish the same trade**, so one deal is kept per pair of clubs
   per day.

### The NBA, which is built

`stats.nba.com/stats/leaguetransactions` returns 404 and does not exist. The
data is in a static file instead:

    https://stats.nba.com/js/data/playermovement/NBA_Player_Movement.json

It holds every player movement since 2015, about 9700 rows, with
`Transaction_Type`, `TEAM_SLUG`, `PLAYER_SLUG`, `TRANSACTION_DATE`, and a
sentence. A trade row reads "LA Clippers received forward Johni Broome from
Philadelphia 76ers", and the club on the row is always the receiving side, so
direction is data. Only the origin club is read from the sentence, against the
closed set of 30.

Two traps:

1. **stats.nba.com blocks a plain request.** It needs the headers its own site
   sends, including `x-nba-stats-token`. Without them the file comes back as a
   block page.
2. **One trade writes a row per piece**, including draft considerations with no
   player at all. One deal is kept per pair of clubs per day, and a row that
   names a player wins, because "Johni Broome" beats "draft consideration".

Three further routes were tested and all failed:

* **ESPN news with team tags.** An article carries structured team ids, so the
  idea was that a trade would tag both clubs. It does not work. 32 of 50 MLB
  articles tag exactly two clubs, because a game preview names two clubs. The
  NHL feed even tags a hockey story with the Miami Heat.
* **ProSportsTransactions.** Blocks automated requests.

**To build it, something has to supply the data:**

1. **A paid provider.** Sportradar and Stats Perform both carry transactions for
   all four leagues, with the clubs as fields. This is the only route that gives
   full automation.
2. **A site that publishes structured moves**, such as PuckPedia or Spotrac.
   Neither offers a documented free API, so this means scraping, which breaks
   without warning.
3. **The push route.** Already built, and it covers the NBA today.

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
