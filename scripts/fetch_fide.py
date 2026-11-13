"""Download the current FIDE players lists into players/YYYYMM/ after validating them.

YYYYMM comes from the file date inside FIDE's zip, so a late FIDE release is not
filed under the wrong month. An existing month folder is left alone unless --force.

Prints `changed=true|false` and `month=YYYYMM`; also appends them to $GITHUB_OUTPUT.
Exit code is non-zero if a download or a validation check fails (nothing is written).
"""
from __future__ import annotations

import argparse
import io
import os
import re
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.index import _COLS, PlayerIndex  # noqa: E402

BASE = "https://ratings.fide.com/download/"
# FIDE file name -> name stored in players/YYYYMM/
FILES = {"txt": ("players_list.zip", "players_list_txt.zip"),
         "xml": ("players_list_xml.zip", "players_list_xml.zip")}
HEADER_TOKENS = {"fed": "Fed", "sex": "Sex", "title": "Tit", "w_title": "WTit",
                 "o_title": "OTit", "foa_title": "FOA", "rating": "SRtng", "games": "SGm",
                 "k": "SK", "rapid_rating": "RRtng", "rapid_games": "RGm", "rapid_k": "Rk",
                 "blitz_rating": "BRtng", "blitz_games": "BGm", "blitz_k": "BK",
                 "birthday": "B-day", "flag": "Flag"}
MIN_RATED = 500_000  # 202611 had 800,250; far fewer means a broken file


def download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "fide-lookup-refresh"})
    with urllib.request.urlopen(req, timeout=600) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)


def only_member(z: zipfile.ZipFile, suffix: str) -> zipfile.ZipInfo:
    members = [i for i in z.infolist() if i.filename.endswith(suffix)]
    if len(members) != 1:
        raise ValueError(f"expected one *{suffix} in zip, found {[i.filename for i in z.infolist()]}")
    return members[0]


def check_header(header: str) -> None:
    """The app slices fixed-width columns; fail loudly if FIDE moved any."""
    problems = []
    if not header.startswith("ID Number") or header.find("Name") != 15:
        problems.append("ID/Name")
    for key, tok in HEADER_TOKENS.items():
        m = re.search(r"(?<!\S)" + re.escape(tok) + r"(?!\S)", header)
        if not m or m.start() != _COLS[key][0]:
            problems.append(f"{tok} at {m.start() if m else 'missing'}, expected {_COLS[key][0]}")
    if problems:
        raise ValueError("txt column layout changed: " + "; ".join(problems))


def validate_txt(path: Path) -> tuple[str, int]:
    """Return (YYYYMM, rated player count)."""
    with zipfile.ZipFile(path) as z:
        info = only_member(z, ".txt")
        with z.open(info) as f:
            check_header(io.TextIOWrapper(f, encoding="utf-8", errors="replace").readline())
    month = f"{info.date_time[0]:04d}{info.date_time[1]:02d}"
    rated = len(PlayerIndex.from_zip(str(path)))
    if rated < MIN_RATED:
        raise ValueError(f"only {rated} rated players (expected >= {MIN_RATED})")
    return month, rated


def validate_xml(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        info = only_member(z, ".xml")
        with z.open(info) as f:
            if b"<playerslist>" not in f.read(200):
                raise ValueError("xml does not start with <playerslist>")
    return f"{info.date_time[0]:04d}{info.date_time[1]:02d}"


def emit(**kv: str) -> None:
    lines = [f"{k}={v}" for k, v in kv.items()]
    print("\n".join(lines))
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write("\n".join(lines) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=str(ROOT / "players"))
    ap.add_argument("--formats", nargs="+", default=["txt"], choices=list(FILES),
                    help="txt only by default; the service never reads the xml list")
    ap.add_argument("--force", action="store_true", help="replace an existing month folder")
    args = ap.parse_args()
    if "txt" not in args.formats:
        ap.error("txt is required: the service reads it")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        got: dict[str, Path] = {}
        for fmt in args.formats:
            remote, _ = FILES[fmt]
            got[fmt] = tmp / remote
            print(f"downloading {BASE + remote}", flush=True)
            download(BASE + remote, got[fmt])

        month, rated = validate_txt(got["txt"])
        print(f"txt ok: month {month}, {rated} rated players", flush=True)
        target = Path(args.root) / month
        if target.exists() and not args.force:
            print(f"{target} already exists; nothing to do")
            emit(changed="false", month=month)
            return 0
        if "xml" in got:
            xml_month = validate_xml(got["xml"])
            if xml_month != month:
                raise ValueError(f"xml is from {xml_month}, txt from {month}")
            print("xml ok", flush=True)

        target.mkdir(parents=True, exist_ok=True)
        for fmt, path in got.items():
            shutil.move(str(path), target / FILES[fmt][1])
    emit(changed="true", month=month)
    return 0


if __name__ == "__main__":
    sys.exit(main())
