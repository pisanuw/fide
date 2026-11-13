# fide

Minimal FIDE player lookup. In-memory index, FastAPI, one static HTML page.

    GET /api/players?q=carlsen                      up to 5 matches, JSON
    GET /api/players?q=magnus carl&limit=3&format=xml
    GET /api/players?q=1503014&format=txt&download=1   FIDE id, attachment
    GET /api/players/fide/1503014                   exact FIDE id (404 if none)

`format` is `json` (default), `xml` or `txt` (tab-separated, header row). All fields are always returned.
`download=1` adds `Content-Disposition: attachment`. `limit` is 1-5 (default 5).

Search: all words must match. A query equal to the whole name (any word order, 2+ words) comes first, then prefix-of-a-word matches, then substring matches; each group is
ordered by standard, then rapid, then blitz rating. Accents and punctuation are ignored. An all-digit `q` is a FIDE id: exact match first, then ids that start with those digits (3+ digits), best rating first.

Only players with a rating in any list are indexed (about 800k of 1.95M); set `INCLUDE_UNRATED=1` for all.
Data: newest `players/*/players_list_txt.zip`, loaded at startup (~8 s, ~320 MB RAM).
Rate limit: `RATE_LIMIT` requests per `RATE_WINDOW` seconds per IP (60 / 60), 429 with `Retry-After` beyond that.
No US Chess ID: FIDE's lists do not contain it.

Run: `pip install -r requirements-dev.txt && uvicorn app.main:app` ; test: `pytest`. Deploy: `render.yaml`.
To update the data, add a new `players/YYYYMM/players_list_txt.zip` and redeploy.
