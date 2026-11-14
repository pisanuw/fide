# BRIEFING
Goal: minimalist web service; look up FIDE players by partial name or FIDE id; GET one URL for up to 5 matches;
download json/xml/txt (per player and for all results). Speed is the priority.
Decisions: Python/FastAPI on Render, plain HTML, in-memory index (no database). Index = players with any rating.
Public, per-IP rate limit. Live at https://fide-lookup.hintwise.org (Render free plan, cold starts accepted).
Monthly data refresh: launchd job on halflife (GitHub runners cannot reach FIDE) commits players/YYYYMM/players_list_txt.zip to main; Render redeploys on push.
US Chess ID: only for players on US Chess top-100 lists, matched to FIDE by name (data/uschess_fide.tsv).
API consumers: Chess TD (https://chesstd.hintwise.org) calls the API from the browser (CORS); limit up to 30; fed/born filters.
