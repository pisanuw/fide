# BRIEFING
Goal: minimalist web service; look up FIDE players by partial name or FIDE id; GET one URL for up to 5 matches;
download json/xml/txt (per player and for all results). Speed is the priority.
Decisions: Python/FastAPI on Render, plain HTML, in-memory index (no database). Index = players with any rating.
Public, per-IP rate limit. Live at https://fide-lookup.hintwise.org (Render free plan, cold starts accepted).
Monthly data refresh via GitHub Action committing players/YYYYMM to main; Render redeploys on push.
Non-goals for now: US Chess ID (not in FIDE data; revisit with a live lookup + cache).
