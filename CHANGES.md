
2026-11-13 [decision] No US Chess ID for now (absent from FIDE lists); Render + in-memory index; Python/FastAPI; public with per-IP rate limit.
2026-11-13 [decision] Index only players rated in any list (800k of 1.95M); literal "rated or active" filter kept everyone.
2026-11-13 [code] Vertical slice: app/index.py, app/main.py, static/index.html, tests, render.yaml. Search ~0.3-30 ms.
2026-11-13 [decision] Exact whole-name match ranks first (2+ words, any order); Render free plan first, starter if OOM.
