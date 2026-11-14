"""In-memory FIDE player index.

Players are sorted best-rating-first, so scanning the search blob front to back
yields results already ranked and lets a query stop once it has enough.

Name search tiers (each tier is rating-ordered; tiers are concatenated):
  0. the query words are exactly the name's words, in any order (2+ words only)
  1. every query word is a prefix of some name word
  2. every query word is a substring somewhere in the name (fallback)
The total count is the size of tier 2's set, which contains the other tiers.

Digit queries are FIDE or US Chess ids: exact matches of either kind first,
then ids of either kind starting with those digits (3+ digits), best rating
first. US Chess ids come from an optional mapping (data/uschess_fide.tsv).

Optional filters: fed (federation code) and born (birth year).
"""
from __future__ import annotations

import csv
import glob
import heapq
import io
import os
import unicodedata
import zipfile
from array import array
from bisect import bisect_left, bisect_right
from collections import Counter
from itertools import chain

# Fixed-width columns of players_list_foa.txt (from its header line).
_COLS = {
    "fed": (76, 80), "sex": (80, 84), "title": (84, 89), "w_title": (89, 94),
    "o_title": (94, 109), "foa_title": (109, 113),
    "rating": (113, 119), "games": (119, 123), "k": (123, 126),
    "rapid_rating": (126, 132), "rapid_games": (132, 136), "rapid_k": (136, 139),
    "blitz_rating": (139, 145), "blitz_games": (145, 149), "blitz_k": (149, 152),
    "birthday": (152, 158), "flag": (158, 170),
}
_INT_FIELDS = {"rating", "games", "k", "rapid_rating", "rapid_games", "rapid_k",
               "blitz_rating", "blitz_games", "blitz_k", "birthday"}
_REC_FIELDS = ["fideid", "name"] + list(_COLS)          # stored per player
FIELDS = _REC_FIELDS + ["uschess_id"]                    # returned (uschess_id may be None)
_RATING_COLS = [_COLS[c] for c in ("rating", "rapid_rating", "blitz_rating")]
SEP = "\x1f"

# With a filter whose player list is at most this long, walk that list instead
# of scanning the whole name blob. 30k covers every birth year (~27k max) and all
# but the largest federations (IND, RUS, FRA, ESP, GER: 40-75k).
FILTER_LIST_MAX = 30_000


def fold(s: str) -> str:
    """Lowercase, strip accents, turn punctuation into spaces."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return "".join(c if c.isalnum() else " " for c in s)


def find_data_file(root: str) -> str:
    """Newest players_list_txt.zip under root (the monthly folders sort by name)."""
    if os.path.isfile(root):
        return root
    hits = sorted(glob.glob(os.path.join(root, "**", "players_list_txt.zip"), recursive=True))
    if not hits:
        raise FileNotFoundError(f"no players_list_txt.zip under {root}")
    return hits[-1]


def _group(keys: array) -> dict[int, array]:
    """key -> array of the positions holding it, ascending; arrays sized exactly."""
    counts = Counter(keys)
    groups = {k: array("I", [0]) * c for k, c in counts.items()}
    fill = dict.fromkeys(counts, 0)
    for i, k in enumerate(keys):
        groups[k][fill[k]] = i
        fill[k] += 1
    return groups


def load_uschess_map(path: str) -> dict[int, int]:
    """{FIDE id: US Chess id} from a TSV with uschess_id and fide_id columns; {} if absent."""
    if not os.path.isfile(path):
        return {}
    out: dict[int, int] = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            if row.get("uschess_id", "").isdigit() and row.get("fide_id", "").isdigit():
                out[int(row["fide_id"])] = int(row["uschess_id"])
    return out


class PlayerIndex:
    def __init__(self, lines, include_unrated: bool = False, uschess: dict[int, int] | None = None):
        """lines: raw fixed-width data lines (no header)."""
        rows = []
        for raw in lines:
            if len(raw) < 80:
                continue
            ratings = [int(raw[a:b].strip() or 0) for a, b in _RATING_COLS]
            if not include_unrated and not any(ratings):
                continue
            fid = raw[:15].strip()
            name = raw[15:76].strip()
            rec = SEP.join([fid, name] + [raw[a:b].strip() for a, b in _COLS.values()])
            rows.append((-ratings[0], -ratings[1], -ratings[2], name, rec))
        rows.sort()
        self.records: list[str] = []
        ids: list[int] = []
        blob_parts: list[str] = []
        offsets = array("I")
        self.feds: list[str] = []          # federation code by number
        fed_num: dict[str, int] = {}
        # preallocated: growing hundreds of arrays one item at a time fragments the heap (~40 MB)
        self.fed_of = array("H", [0]) * len(rows)   # line -> federation number
        self.born_of = array("H", [0]) * len(rows)  # line -> birth year (0 = unknown)
        pos = 0
        # federation and birth year are read back from the record after sorting: keeping
        # them in `rows` costs ~65 MB that fragmentation never gives back
        fed_at, born_at = FIELDS.index("fed"), FIELDS.index("birthday")
        for i, (_, _, _, name, rec) in enumerate(rows):
            self.records.append(rec)
            parts = rec.split(SEP)
            fed = parts[fed_at].upper()
            born = int(parts[born_at]) if parts[born_at].isdigit() else 0
            fid = rec.split(SEP, 1)[0]
            ids.append(int(fid) if fid.isdigit() else -1)
            line = " " + " ".join(fold(name).split()) + "\n"
            offsets.append(pos)
            pos += len(line)
            blob_parts.append(line)
            if fed not in fed_num:
                fed_num[fed] = len(self.feds)
                self.feds.append(fed)
            self.fed_of[i] = fed_num[fed]
            self.born_of[i] = born if 0 < born < 65536 else 0
        del rows
        self.fed_num = fed_num
        self.by_fed = _group(self.fed_of)    # key -> lines, in rating order like the blob
        self.by_born = _group(self.born_of)
        order = sorted(range(len(ids)), key=ids.__getitem__)
        self.id_sorted = array("q", (ids[i] for i in order))  # FIDE id -> position, by bisect
        self.id_pos = array("I", order)
        self.blob = "".join(blob_parts)
        self.offsets = offsets
        self.set_uschess(uschess or {})

    def set_uschess(self, fide_to_uschess: dict[int, int]) -> None:
        """US Chess ids for FIDE players: {fide id: US Chess id}. Unknown FIDE ids are ignored."""
        self.uschess_of: dict[int, int] = {}          # line -> US Chess id
        pairs = []
        for fid, uid in fide_to_uschess.items():
            pos = self._pos_of_id(fid)
            if pos is not None:
                self.uschess_of[pos] = uid
                pairs.append((uid, pos))
        pairs.sort()
        self.us_sorted = array("q", (u for u, _ in pairs))
        self.us_pos = array("I", (p for _, p in pairs))

    @classmethod
    def from_zip(cls, path: str, include_unrated: bool = False,
                 uschess: dict[int, int] | None = None) -> "PlayerIndex":
        with zipfile.ZipFile(path) as z:
            member = next(n for n in z.namelist() if n.endswith(".txt"))
            with z.open(member) as f:
                text = io.TextIOWrapper(f, encoding="utf-8", errors="replace", newline="")
                next(text)  # header
                return cls((l.rstrip("\r\n") for l in text), include_unrated, uschess)

    def __len__(self) -> int:
        return len(self.records)

    # -- record access -----------------------------------------------------
    def record(self, i: int) -> dict:
        d: dict = dict(zip(_REC_FIELDS, self.records[i].split(SEP)))
        for key in _INT_FIELDS:
            v = d[key]
            d[key] = int(v) if v.isdigit() else 0
        d["fideid"] = int(d["fideid"])
        d["uschess_id"] = self.uschess_of.get(i)
        return d

    def _pos_of_id(self, fid: int) -> int | None:
        j = bisect_left(self.id_sorted, fid)
        if j < len(self.id_sorted) and self.id_sorted[j] == fid:
            return self.id_pos[j]
        return None

    def _pos_of_uschess(self, uid: int) -> int | None:
        j = bisect_left(self.us_sorted, uid)
        if j < len(self.us_sorted) and self.us_sorted[j] == uid:
            return self.us_pos[j]
        return None

    def get_uschess(self, uid: int) -> dict | None:
        i = self._pos_of_uschess(uid)
        return None if i is None else self.record(i)

    def get_fide(self, fid: int) -> dict | None:
        i = self._pos_of_id(fid)
        return None if i is None else self.record(i)

    def _line(self, ls: int) -> str:
        offsets = self.offsets
        end = offsets[ls + 1] if ls + 1 < len(offsets) else len(self.blob)
        return self.blob[offsets[ls]:end]

    # -- filters -----------------------------------------------------------
    def _filter(self, fed: str | None, born: int | None):
        """None: no filter. False: matches nothing. Else (fed number | None, born | None)."""
        if not fed and not born:
            return None
        fc = None
        if fed:
            fc = self.fed_num.get(fed.strip().upper())
            if fc is None:
                return False
        if born and born not in self.by_born:
            return False
        return fc, born or None

    def _ok(self, flt):
        fc, born = flt
        fed_of, born_of = self.fed_of, self.born_of
        if fc is not None and born is not None:
            return lambda i: fed_of[i] == fc and born_of[i] == born
        if fc is not None:
            return lambda i: fed_of[i] == fc
        return lambda i: born_of[i] == born

    # -- search ------------------------------------------------------------
    def find(self, q: str, limit: int = 5, fed: str | None = None, born: int | None = None,
             cap: int = 1000) -> tuple[list[dict], int, bool]:
        """(up to `limit` players, total matching players, whether total is exact).
        Name totals are counted up to `cap`; id totals are always exact."""
        q = q.strip()
        flt = self._filter(fed, born)
        if not q or flt is False:
            return [], 0, True
        if q.isdigit():
            ids, total, exact = self._find_id(q, limit, flt)
        else:
            tokens = fold(q).split()
            if not tokens or max(len(t) for t in tokens) < 2:
                return [], 0, True
            ids, total, exact = self._find_names(tokens, limit, flt, cap)
        return [self.record(i) for i in ids], total, exact

    def search(self, q: str, limit: int = 5, fed: str | None = None, born: int | None = None) -> list[dict]:
        return self.find(q, limit, fed, born)[0]

    def count(self, q: str, cap: int = 1000, fed: str | None = None, born: int | None = None) -> tuple[int, bool]:
        _, total, exact = self.find(q, 1, fed, born, cap)
        return total, exact

    @staticmethod
    def _prefix_ranges(sorted_ids: array, positions: array, q: str) -> list[array]:
        """Positions of ids that start with the digits q and are longer than q."""
        if len(q) < 3:  # 1-2 digits are too ambiguous for prefix matching
            return []
        base, out = int(q), []
        for k in range(1, 10 - len(q) + 1):  # ids have at most 9 digits
            lo = bisect_left(sorted_ids, base * 10 ** k)
            hi = bisect_left(sorted_ids, (base + 1) * 10 ** k)
            if hi > lo:
                out.append(positions[lo:hi])
        return out

    def _find_id(self, q: str, limit: int, flt) -> tuple[list[int], int, bool]:
        base = int(q)
        exact = {p for p in (self._pos_of_id(base), self._pos_of_uschess(base)) if p is not None}
        fide_ranges = self._prefix_ranges(self.id_sorted, self.id_pos, q)
        us_ranges = self._prefix_ranges(self.us_sorted, self.us_pos, q)
        if flt is None and not us_ranges and not (exact - {self._pos_of_id(base)}):
            # FIDE ids only: the exact id cannot be in its own prefix ranges; count by arithmetic
            total = len(exact) + sum(len(r) for r in fide_ranges)
            prefix = heapq.nsmallest(limit, chain.from_iterable(fide_ranges))
        else:
            ok = self._ok(flt) if flt is not None else (lambda i: True)
            exact = {p for p in exact if ok(p)}
            cands = {p for p in chain.from_iterable(fide_ranges + us_ranges) if ok(p)} - exact
            total = len(exact) + len(cands)
            prefix = heapq.nsmallest(limit, cands)
        return (sorted(exact) + prefix)[:limit], total, True

    def _exact_two(self, tokens: list[str], ok, limit: int) -> list[int]:
        """Lines whose words are exactly the two tokens, either order, by direct search.
        Anchored on the preceding newline so ' magnus carlsen' does not match the end
        of ' sanico magnus carlsen'."""
        blob, offsets = self.blob, self.offsets
        hits = set()
        a, b = tokens
        for body in {f" {a} {b}\n", f" {b} {a}\n"}:
            if blob.startswith(body):
                hits.add(0)
            needle = "\n" + body
            p = blob.find(needle)
            while p >= 0:
                hits.add(bisect_right(offsets, p + 1) - 1)
                p = blob.find(needle, p + 1)
        return sorted(i for i in hits if ok is None or ok(i))[:limit]

    def _candidates(self, driver: str, flt):
        """(line number, line text) in rating order, for every line that may match."""
        blob, offsets = self.blob, self.offsets
        n, end = len(offsets), len(blob)
        if flt is not None:
            fc, born = flt
            lists = ([self.by_fed[fc]] if fc is not None else []) + \
                    ([self.by_born[born]] if born is not None else [])
            smallest = min(lists, key=len)
            if len(smallest) <= FILTER_LIST_MAX:
                for ls in smallest:
                    yield ls, blob[offsets[ls]:offsets[ls + 1] if ls + 1 < n else end]
                return
        start = 0
        while True:
            p = blob.find(driver, start)
            if p < 0:
                return
            ls = bisect_right(offsets, p) - 1
            le = offsets[ls + 1] if ls + 1 < n else end
            yield ls, blob[offsets[ls]:le]
            start = le

    def _find_names(self, tokens: list[str], limit: int, flt, cap: int) -> tuple[list[int], int, bool]:
        ok = self._ok(flt) if flt is not None else None
        exact_ids: list[int] = []
        if len(tokens) == 2:
            exact_ids = self._exact_two(tokens, ok, limit)
        seen = set(exact_ids)
        # 3+ words: exact matches are found during the pass, which then cannot stop early
        exact_in_pass = len(tokens) >= 3
        want = sorted(tokens)
        pre = [" " + t for t in tokens]
        driver = max(tokens, key=len)
        ex3: list[int] = []
        prefix: list[int] = []
        sub: list[int] = []
        count = 0
        for ls, line in self._candidates(driver, flt):
            if not all(t in line for t in tokens):
                continue
            if ok is not None and not ok(ls):
                continue
            if count < cap:
                count += 1
            if ls not in seen:
                if exact_in_pass and sorted(line.split()) == want:
                    if len(ex3) < limit:
                        ex3.append(ls)
                elif all(p in line for p in pre):
                    if len(prefix) < limit:
                        prefix.append(ls)
                elif len(sub) < limit:
                    sub.append(ls)
            if count >= cap and len(prefix) >= limit and not exact_in_pass:
                break
        return (exact_ids + ex3 + prefix + sub)[:limit], count, count < cap
