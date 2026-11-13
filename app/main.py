"""FastAPI service: GET /api/players?q=...&format=json|xml|txt"""
from __future__ import annotations

import os
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from xml.sax.saxutils import escape

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .index import FIELDS, PlayerIndex, find_data_file

ROOT = Path(__file__).resolve().parent.parent
DATA = os.environ.get("FIDE_DATA", str(ROOT / "players"))
INCLUDE_UNRATED = os.environ.get("INCLUDE_UNRATED", "0") == "1"
RATE_LIMIT = int(os.environ.get("RATE_LIMIT", "60"))  # requests per window per IP
RATE_WINDOW = float(os.environ.get("RATE_WINDOW", "60"))
DEFAULT_LIMIT = 5
MAX_LIMIT = 30
# Browser origins allowed to call the API directly (comma-separated)
CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "https://chesstd.hintwise.org").split(",") if o.strip()]

state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    if "index" not in state:  # tests may inject one
        path = find_data_file(DATA)
        t = time.time()
        state["index"] = PlayerIndex.from_zip(path, INCLUDE_UNRATED)
        state["source"] = Path(path).parent.name
        print(f"loaded {len(state['index'])} players from {path} in {time.time() - t:.1f}s", flush=True)
    yield


app = FastAPI(title="FIDE player lookup", lifespan=lifespan)

# -- per-IP rate limiting (in memory, sliding window) ----------------------
_hits: dict[str, deque] = {}


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:  # Render appends the real client address last-but-trusted; take the first
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "?"


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        now = time.monotonic()
        ip = client_ip(request)
        q = _hits.setdefault(ip, deque())
        while q and now - q[0] > RATE_WINDOW:
            q.popleft()
        if len(q) >= RATE_LIMIT:
            retry = max(1, int(RATE_WINDOW - (now - q[0])))
            return JSONResponse({"detail": "rate limit exceeded"}, status_code=429,
                                headers={"Retry-After": str(retry)})
        q.append(now)
        if len(_hits) > 50_000:  # bound memory under many-IP floods
            for k in [k for k, v in _hits.items() if not v or now - v[-1] > RATE_WINDOW]:
                del _hits[k]
    return await call_next(request)


# Added after the rate limiter so it wraps it: 429 responses carry CORS headers too,
# otherwise a browser reports a CORS error instead of the 429.
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET"],
    expose_headers=["X-Total-Count", "X-Total-Count-Exact", "Retry-After", "Content-Disposition"],
    max_age=86400,
)


# -- formatting ------------------------------------------------------------
def to_txt(players: list[dict]) -> str:
    lines = ["\t".join(FIELDS)]
    lines += ["\t".join(str(p[f]) for f in FIELDS) for p in players]
    return "\n".join(lines) + "\n"


def to_xml(players: list[dict]) -> str:
    out = ['<?xml version="1.0" encoding="UTF-8"?>', "<playerslist>"]
    for p in players:
        out.append("<player>")
        out += [f"<{f}>{escape(str(p[f]))}</{f}>" for f in FIELDS]
        out.append("</player>")
    out.append("</playerslist>")
    return "\n".join(out) + "\n"


def render(players: list[dict], fmt: str, download: bool, stem: str) -> Response:
    if fmt == "json":
        resp: Response = JSONResponse(players)
    elif fmt == "xml":
        resp = Response(to_xml(players), media_type="application/xml")
    else:
        resp = Response(to_txt(players), media_type="text/plain; charset=utf-8")
    if download:
        resp.headers["Content-Disposition"] = f'attachment; filename="{stem}.{fmt}"'
    return resp


Format = Query("json", pattern="^(json|xml|txt)$")


# -- routes ----------------------------------------------------------------
@app.get("/api/players")
def players(q: str = Query(..., min_length=1, max_length=100),
            limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
            fed: str | None = Query(None, pattern="^[A-Za-z]{3}$", description="federation code, e.g. NOR"),
            born: int | None = Query(None, ge=1900, le=2100, description="birth year"),
            format: str = Format, download: bool = False):
    found, total, exact = state["index"].find(q, limit, fed, born)
    resp = render(found, format, download, "fide-players")
    # total players matching q (shown + not shown); capped at 1000 for names
    resp.headers["X-Total-Count"] = str(max(total, len(found)))
    resp.headers["X-Total-Count-Exact"] = "true" if exact else "false"
    return resp


@app.get("/api/players/fide/{fide_id}")
def by_fide(fide_id: int, format: str = Format, download: bool = False):
    p = state["index"].get_fide(fide_id)
    if p is None:
        raise HTTPException(404, "no such FIDE id")
    return render([p], format, download, f"fide-{fide_id}")


@app.get("/api/health")
def health():
    return {"players": len(state["index"]), "source": state.get("source")}


@app.get("/")
def home():
    return FileResponse(ROOT / "static" / "index.html")
