"""US Chess top-100 lists -> US Chess id to FIDE id mapping (data/uschess_fide.tsv).

  python scripts/uschess_top100.py fetch CACHE_DIR    download every top-100 list (skips cached ones)
  python scripts/uschess_top100.py match CACHE_DIR    match players to the FIDE list, write data/uschess_fide.tsv

US Chess's lists carry no FIDE id, so players are matched by name: the folded
words of "first last" must equal the FIDE name's words (any order). A match also
needs the FIDE federation to be US Chess's country code or USA, the sex not to
conflict, and a FIDE birth year to fit the age lists the player is on (e.g.
"Regular12", "65Plus"). Names that fit several FIDE players, or only players in another
federation, are skipped and reported: a wrong id is worse than a missing one.

Note: ratings.uschess.org's robots.txt disallows automated access. The owner of
this project authorized fetching these lists (2026-11-14). Keep requests minimal:
one per list, 2 s apart, cached.
"""
from __future__ import annotations

import csv
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.index import FIELDS, SEP, PlayerIndex, find_data_file, fold  # noqa: E402

API = "https://ratings-api.uschess.org/api/v1/top-players/"
OUT = ROOT / "data" / "uschess_fide.tsv"
DELAY = 2.0

# from the ratings.uschess.org app (Top100 category list)
_KINDS = ["Regular", "Quick", "Blitz"]
CATEGORIES = []
for _base in ["RegularOverall", "RegularAnyFed", "WomensRegular", "WomensRegularAnyFed"]:
    CATEGORIES.append(_base)
for _age in ["65Plus", "50Plus", "Under21", "18", "17", "16", "15", "14", "13", "12", "11", "10", "9", "8", "7andUnder"]:
    for _w in ["", "Womens"]:
        CATEGORIES += [f"{_w}Regular{_age}", f"{_w}Regular{_age}AnyFed"]
for _k in ["Quick", "Blitz"]:
    CATEGORIES += [f"{_k}Overall", f"{_k}AnyFed", f"Womens{_k}", f"Womens{_k}AnyFed"]
    for _age in ["65Plus", "50Plus", "Under21", "Under16", "Under13"]:
        for _w in ["", "Womens"]:
            CATEGORIES += [f"{_w}{_k}{_age}", f"{_w}{_k}{_age}AnyFed"]
for _k in ["OnlineRegular", "OnlineQuick", "OnlineBlitz"]:
    CATEGORIES += [f"{_k}Overall", f"{_k}AnyFed", f"Womens{_k}", f"Womens{_k}AnyFed"]
    for _age in ["50Plus", "18to49", "Under18"]:
        for _w in ["", "Womens"]:
            CATEGORIES += [f"{_w}{_k}{_age}", f"{_w}{_k}{_age}AnyFed"]


def fetch(cache: Path) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    todo = [c for c in CATEGORIES if not (cache / f"{c}.json").exists()]
    print(f"{len(CATEGORIES)} lists, {len(todo)} to fetch", flush=True)
    for n, cat in enumerate(todo, 1):
        req = urllib.request.Request(API + cat, headers={"Accept": "application/json",
                                                         "User-Agent": "fide-lookup (top-100 id mapping)"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read()
            json.loads(body)
            (cache / f"{cat}.json").write_bytes(body)
            print(f"{n}/{len(todo)} {cat} ok", flush=True)
        except (urllib.error.URLError, ValueError) as e:
            print(f"{n}/{len(todo)} {cat} FAILED: {e}", flush=True)
        time.sleep(DELAY)


def birth_range(category: str, report_year: int) -> tuple[int, int]:
    """Birth years an age-group list implies, one year of slack each side; (0, 9999) if none."""
    c = re.sub(r"^(Womens)?(Online)?(Regular|Quick|Blitz)", "", category).replace("AnyFed", "")
    y = report_year
    if m := re.fullmatch(r"(\d+)", c):                 # exactly N years old
        n = int(m.group(1))
        return y - n - 2, y - n + 1
    if m := re.fullmatch(r"Under(\d+)", c):            # younger than N
        return y - int(m.group(1)) - 1, 9999
    if c == "7andUnder":
        return y - 9, 9999
    if m := re.fullmatch(r"(\d+)Plus", c):             # N or older
        return 0, y - int(m.group(1)) + 1
    if m := re.fullmatch(r"(\d+)to(\d+)", c):
        return y - int(m.group(2)) - 2, y - int(m.group(1)) + 1
    return 0, 9999


def load_lists(cache: Path) -> dict[str, dict]:
    """US Chess id -> player; the birth-year range is narrowed by every age list they are on."""
    players: dict[str, dict] = {}
    for f in sorted(cache.glob("*.json")):
        d = json.loads(f.read_bytes())
        year = int(str(d.get("reportDate") or "2026")[:4])
        lo, hi = birth_range(f.stem, year)
        for p in d.get("topPlayers") or []:
            pid = str(p.get("id", "")).strip()
            if not pid.isdigit():
                continue
            if pid not in players:
                players[pid] = {"id": pid, "first": (p.get("firstName") or "").strip(),
                                "last": (p.get("lastName") or "").strip(),
                                "country": (p.get("countryCode") or "").strip().upper(),
                                "sex": {"Male": "M", "Female": "F"}.get(p.get("gender"), ""),
                                "born": (0, 9999)}
            b = players[pid]["born"]
            players[pid]["born"] = (max(b[0], lo), min(b[1], hi))
    return players


def match_players(us: dict[str, dict], ix: PlayerIndex) -> dict:
    """Match US Chess players to FIDE records. Returns rows and the reasons others were skipped."""
    fi = {f: FIELDS.index(f) for f in ("fideid", "name", "fed", "sex", "birthday")}
    by_name: dict[tuple, list] = defaultdict(list)
    for rec in ix.records:
        parts = rec.split(SEP)
        by_name[tuple(sorted(fold(parts[fi["name"]]).split()))].append(
            (int(parts[fi["fideid"]]), parts[fi["name"]], parts[fi["fed"]], parts[fi["sex"]],
             int(parts[fi["birthday"]]) if parts[fi["birthday"]].isdigit() else 0))

    rows, unmatched, ambiguous, other_fed = [], [], [], []
    for p in us.values():
        key = tuple(sorted(fold(f"{p['first']} {p['last']}").split()))
        cands = by_name.get(key, [])
        # precision over recall: a wrong id is worse than a missing one. The FIDE federation
        # must be US Chess's country code or USA, the sex must not conflict, and a FIDE birth
        # year must fit the age lists the player is on.
        feds = {p["country"] or "USA", "USA"}
        lo, hi = p["born"]
        same = [c for c in cands if c[2] in feds
                and (not p["sex"] or not c[3] or c[3] == p["sex"])
                and (not c[4] or lo <= c[4] <= hi)]
        if len(same) > 1:  # prefer the player's own country code over USA
            own = [c for c in same if c[2] == (p["country"] or "USA")]
            same = own if len(own) == 1 else same
        if len(same) == 1:
            fid, fname, ffed, _, _ = same[0]
            rows.append((p["id"], fid, f"{p['last']}, {p['first']}", fname, ffed, "name+fed+age"))
        elif same:
            ambiguous.append((p, same))
        elif cands:
            other_fed.append((p, cands))
        else:
            unmatched.append(p)

    # one FIDE player must not get two US Chess ids
    per_fide = defaultdict(list)
    for r in rows:
        per_fide[r[1]].append(r)
    dup = {fid for fid, rs in per_fide.items() if len(rs) > 1}
    rows = sorted((r for r in rows if r[1] not in dup), key=lambda r: int(r[0]))
    return {"rows": rows, "unmatched": unmatched, "ambiguous": ambiguous, "no_fit": other_fed,
            "dropped": sum(len(per_fide[f]) for f in dup)}


def match(cache: Path) -> None:
    us = load_lists(cache)
    ix = PlayerIndex.from_zip(find_data_file(str(ROOT / "players")))
    r = match_players(us, ix)
    rows, unmatched, ambiguous, other_fed = r["rows"], r["unmatched"], r["ambiguous"], r["no_fit"]
    OUT.parent.mkdir(exist_ok=True)
    with open(OUT, "w", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["uschess_id", "fide_id", "uschess_name", "fide_name", "fide_fed", "matched_by"])
        w.writerows(rows)
    print(f"US Chess players in lists: {len(us)}")
    print(f"matched: {len(rows)}")
    print(f"no FIDE player with that name: {len(unmatched)}")
    print(f"ambiguous, same name and federation (skipped): {len(ambiguous)}")
    print(f"name found, but federation, sex or birth year does not fit (skipped): {len(other_fed)}")
    for p, c in other_fed[:10]:
        print(f"  no fit: {p['id']} {p['last']}, {p['first']} ({p['country']}) -> {[(x[0], x[1], x[2]) for x in c][:3]}")
    print(f"dropped, two US Chess ids for one FIDE id: {r['dropped']}")
    for p, c in ambiguous[:10]:
        print(f"  ambiguous: {p['id']} {p['last']}, {p['first']} ({p['country']}) -> {[(x[0], x[1], x[2]) for x in c][:4]}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("fetch", "match"):
        sys.exit(__doc__)
    {"fetch": fetch, "match": match}[sys.argv[1]](Path(sys.argv[2]))
