
2026-11-13 [decision] No US Chess ID for now (absent from FIDE lists); Render + in-memory index; Python/FastAPI; public with per-IP rate limit.
2026-11-13 [decision] Index only players rated in any list (800k of 1.95M); literal "rated or active" filter kept everyone.
2026-11-13 [code] Vertical slice: app/index.py, app/main.py, static/index.html, tests, render.yaml. Search ~0.3-30 ms.
2026-11-13 [decision] Exact whole-name match ranks first (2+ words, any order); Render free plan first, starter if OOM.
2026-11-13 [code] Partial FIDE id search: exact id first, then ids starting with the digits (3+ digits), by rating; bisect on sorted ids, ~0.1 ms.
2026-11-13 [doc] README links the live service at https://fide-lookup.hintwise.org.
2026-11-13 [code] Monthly refresh: refresh-fide.yml (3rd and 8th) runs scripts/fetch_fide.py, validates layout and count, commits players/YYYYMM to main.
2026-11-13 [decision] No keep-alive and no paid plan; free Render plan with idle cold starts is accepted.
2026-11-13 [decision] Drop the xml source list (service reads only txt); refresh fetches txt only. History not purged: saves 51 MB once, PR refs keep the blob on GitHub, needs force-push of main.
