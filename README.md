# fide

Minimal FIDE player lookup. In-memory index, FastAPI, one static HTML page.

Live: https://fide-lookup.hintwise.org

    GET /api/players?q=carlsen                      5 matches (default), JSON
    GET /api/players?q=carlsen&fed=NOR&limit=30     up to 30, Norwegian federation only
    GET /api/players?q=smith john&born=1990         born in 1990 only
    GET /api/players?q=magnus carl&limit=3&format=xml
    GET /api/players?q=1503014&format=txt&download=1   FIDE id, attachment
    GET /api/players/fide/1503014                   exact FIDE id (404 if none)

`format` is `json` (default), `xml` or `txt` (tab-separated, header row). All fields are always returned.
`download=1` adds `Content-Disposition: attachment`. `limit` is 1-30 (default 5).
`fed` is a 3-letter FIDE federation code (any case); `born` is a birth year (FIDE lists only the year;
players with no year never match `born`). Filters apply to name and id searches; `q` is still required.
`/api/players` also sets `X-Total-Count` (all players matching `q`, shown or not) and `X-Total-Count-Exact`
(`false` when a name search hit the 1,000 counting cap). The page shows FIDE ids as links to ratings.fide.com/profile/<id>
and "(N more entries match your search)" under the results.

Search: all words must match. A query equal to the whole name (any word order, 2+ words) comes first, then prefix-of-a-word matches, then substring matches; each group is
ordered by standard, then rapid, then blitz rating. Accents and punctuation are ignored. An all-digit `q` is a FIDE id: exact match first, then ids that start with those digits (3+ digits), best rating first.

Only players with a rating in any list are indexed (about 800k of 1.95M); set `INCLUDE_UNRATED=1` for all.
Data: newest `players/*/players_list_txt.zip`, loaded at startup (~8 s, ~320 MB RAM).
CORS: browsers on `CORS_ORIGINS` (comma-separated; default `https://chesstd.hintwise.org`,
`http://localhost:5173`, `http://localhost:4173`) may call the API
directly; `X-Total-Count`, `X-Total-Count-Exact` and `Retry-After` are exposed to them.
Rate limit: `RATE_LIMIT` requests per `RATE_WINDOW` seconds per IP (120 / 60), 429 with `Retry-After` beyond that.
The client IP comes from `CF-Connecting-IP` / `True-Client-IP` (set by Cloudflare in front of Render), never from
`X-Forwarded-For`, which clients can forge. `GET /api/whoami` shows the address a request is counted against.
No US Chess ID: FIDE's lists do not contain it.

Run: `pip install -r requirements-dev.txt && uvicorn app.main:app` ; test: `pytest`. Deploy: `render.yaml`.
Data refresh runs on halflife, not GitHub Actions: GitHub's runners cannot connect to ratings.fide.com
(connection timeout, 2026-11-13). `scripts/install_launchd.sh` installs a launchd job that runs
`scripts/refresh_on_host.sh` on the 3rd and 8th of each month at 09:17 local time, in a dedicated clone on `main`.
It pulls `main`, runs `scripts/fetch_fide.py` (downloads the txt list from https://ratings.fide.com/download_lists.phtml,
checks the column layout and player count, files it under `players/YYYYMM/` using the month from the date inside FIDE's
zip), runs the tests, and commits and pushes to `main` only when a new month arrived; Render redeploys from that push.
`refresh_on_host.sh --check` verifies Python, git push access and FIDE reachability without changing anything.
Log: `~/Library/Logs/fide-refresh.log`.
