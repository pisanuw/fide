"""In-memory FIDE player index.

Players are sorted best-rating-first, so scanning the search blob front to back
yields results already ranked and lets a query stop after `limit` hits.

Search tiers (results of a tier are rating-ordered, tiers are concatenated):
  0. the query words are exactly the name's words, in any order (2+ words only)
  1. every query token is a prefix of some name word
  2. every query token is a substring somewhere in the name (fallback)
"""
from __future__ import annotations

import glob
import io
import os
import unicodedata
import zipfile
from array import array
from bisect import bisect_left, bisect_right

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
FIELDS = ["fideid", "name"] + list(_COLS)
_RATING_COLS = [_COLS[c] for c in ("rating", "rapid_rating", "blitz_rating")]
SEP = "\x1f"


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


class PlayerIndex:
    def __init__(self, lines: list[str], include_unrated: bool = False):
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
        pos = 0
        for i, (_, _, _, name, rec) in enumerate(rows):
            self.records.append(rec)
            fid = rec.split(SEP, 1)[0]
            ids.append(int(fid) if fid.isdigit() else -1)
            line = " " + " ".join(fold(name).split()) + "\n"
            offsets.append(pos)
            pos += len(line)
            blob_parts.append(line)
        del rows
        order = sorted(range(len(ids)), key=ids.__getitem__)
        self.id_sorted = array("q", (ids[i] for i in order))  # FIDE id -> position, by bisect
        self.id_pos = array("I", order)
        self.blob = "".join(blob_parts)
        self.offsets = offsets

    @classmethod
    def from_zip(cls, path: str, include_unrated: bool = False) -> "PlayerIndex":
        with zipfile.ZipFile(path) as z:
            member = next(n for n in z.namelist() if n.endswith(".txt"))
            with z.open(member) as f:
                text = io.TextIOWrapper(f, encoding="utf-8", errors="replace", newline="")
                next(text)  # header
                return cls((l.rstrip("\r\n") for l in text), include_unrated)

    def __len__(self) -> int:
        return len(self.records)

    # -- record access -----------------------------------------------------
    def record(self, i: int) -> dict:
        d: dict = dict(zip(FIELDS, self.records[i].split(SEP)))
        for key in _INT_FIELDS:
            v = d[key]
            d[key] = int(v) if v.isdigit() else 0
        d["fideid"] = int(d["fideid"])
        return d

    def get_fide(self, fid: int) -> dict | None:
        j = bisect_left(self.id_sorted, fid)
        if j < len(self.id_sorted) and self.id_sorted[j] == fid:
            return self.record(self.id_pos[j])
        return None

    # -- search ------------------------------------------------------------
    def _line_of(self, pos: int) -> int:
        return bisect_right(self.offsets, pos) - 1

    def _scan(self, tokens: list[str], prefix: bool, limit: int, seen: set[int],
              exact: bool = False) -> list[int]:
        blob = self.blob
        needles = [(" " + t) if prefix else t for t in tokens]
        # drive the scan with the longest needle (fewest false hits)
        driver = max(needles, key=len)
        others = [n for n in needles if n is not driver]
        out: list[int] = []
        start = 0
        n = len(blob)
        while len(out) < limit:
            p = blob.find(driver, start)
            if p < 0:
                break
            ls = self._line_of(p)
            line_start = self.offsets[ls]
            line_end = self.offsets[ls + 1] if ls + 1 < len(self.offsets) else n
            start = line_end  # at most one hit per player
            if ls in seen:
                continue
            line = blob[line_start:line_end]
            if exact:
                if set(line.split()) == set(tokens):
                    out.append(ls)
            elif all(o in line for o in others):
                out.append(ls)
        return out

    def search(self, q: str, limit: int = 5) -> list[dict]:
        q = q.strip()
        if not q:
            return []
        if q.isdigit():
            hit = self.get_fide(int(q))
            return [hit] if hit else []
        tokens = fold(q).split()
        if not tokens or max(len(t) for t in tokens) < 2:
            return []
        seen: set[int] = set()
        ids: list[int] = []
        # tier 0: the query is the whole name (any word order); single words are skipped
        # because exact one-word names are rare and the extra scan costs ~10 ms
        if len(tokens) > 1:
            ids = self._scan(tokens, True, limit, seen, exact=True)
            seen.update(ids)
        if len(ids) < limit:
            new = self._scan(tokens, True, limit - len(ids), seen)
            ids += new
            seen.update(new)
        if len(ids) < limit:
            ids += self._scan(tokens, False, limit - len(ids), seen)
        return [self.record(i) for i in ids]
