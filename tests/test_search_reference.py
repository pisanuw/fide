"""Compare PlayerIndex.find with a brute-force implementation of the documented rules."""
import random

import pytest

from app.index import PlayerIndex, fold
from tests.test_api import line

WORDS = ["an", "ana", "anna", "berg", "van", "der", "de", "la", "cruz", "carl", "carlsen", "magnus", "son",
         "sonia", "ma", "mari", "maria", "li", "lin", "kumar", "jose", "jos", "smith", "john", "johnson"]
FEDS = ["USA", "NOR", "IND", "ESP"]


def make_players(n=400, seed=7):
    rnd = random.Random(seed)
    players = []
    for i in range(n):
        words = [w.capitalize() for w in rnd.sample(WORDS, rnd.randint(1, 4))]
        name = words[0] + ", " + " ".join(words[1:]) if len(words) > 1 else words[0]
        players.append(dict(fid=100000 + i * 7, name=name, fed=rnd.choice(FEDS),
                            std=rnd.choice([0, rnd.randint(1000, 2800)]), rapid=rnd.randint(0, 2800),
                            born=rnd.choice([1990, 2000, 2010, 0])))
    # tail-match trap: ' magnus carlsen' must not count as an exact match of the longer name
    players.append(dict(fid=1, name="Sanico, Magnus Carlsen", fed="USA", std=2900, rapid=0, born=1990))
    players.append(dict(fid=2, name="Carlsen, Magnus", fed="NOR", std=2800, rapid=0, born=1990))
    return players


def reference(players, q, limit, fed=None, born=None):
    order = sorted(players, key=lambda p: (-p["std"], -p["rapid"], 0, p["name"]))
    order = [p for p in order if p["std"] or p["rapid"]]
    if fed:
        order = [p for p in order if p["fed"] == fed.upper()]
    if born:
        order = [p for p in order if p["born"] == born]
    tokens = fold(q).split()
    if not tokens or max(map(len, tokens)) < 2:
        return [], 0
    words = {p["fid"]: fold(p["name"]).split() for p in order}
    def text(p): return " " + " ".join(words[p["fid"]]) + "\n"
    sub = [p for p in order if all(t in text(p) for t in tokens)]
    exact = [p for p in sub if len(tokens) > 1 and sorted(words[p["fid"]]) == sorted(tokens)]
    prefix = [p for p in sub if p not in exact and all(" " + t in text(p) for t in tokens)]
    rest = [p for p in sub if p not in exact and p not in prefix]
    return [p["fid"] for p in (exact + prefix + rest)[:limit]], len(sub)


@pytest.fixture(scope="module")
def players_and_index():
    players = make_players()
    lines = [line(p["fid"], p["name"], p["fed"], std=p["std"], rapid=p["rapid"], born=p["born"]) for p in players]
    return players, PlayerIndex(lines)


QUERIES = ["an", "ann", "ma", "magnus carlsen", "carlsen magnus", "van der berg", "berg van", "de la", "son",
           "john smith", "smith", "jos", "ar", "an ma", "li lin", "maria jose", "cruz", "zz", "an an", "carl"]


@pytest.mark.parametrize("q", QUERIES)
@pytest.mark.parametrize("limit", [1, 5, 30])
@pytest.mark.parametrize("flt", [{}, {"fed": "nor"}, {"born": 2010}, {"fed": "IND", "born": 1990}])
def test_matches_reference(players_and_index, q, limit, flt):
    players, ix = players_and_index
    want_ids, want_total = reference(players, q, limit, **flt)
    got, total, exact = ix.find(q, limit, cap=10_000, **flt)
    assert [p["fideid"] for p in got] == want_ids
    assert (total, exact) == (want_total, True)


def test_cap(players_and_index):
    players, ix = players_and_index
    _, want_total = reference(players, "an", 5)
    assert want_total > 20
    assert ix.find("an", 5, cap=20)[1:] == (20, False)


def test_filter_list_path_matches_scan_path(players_and_index, monkeypatch):
    _, ix = players_and_index
    import app.index as m
    for q in QUERIES:
        for flt in ({"fed": "NOR"}, {"born": 2000}):
            monkeypatch.setattr(m, "FILTER_LIST_MAX", 10**9)
            a = ix.find(q, 30, cap=10_000, **flt)
            monkeypatch.setattr(m, "FILTER_LIST_MAX", 0)
            b = ix.find(q, 30, cap=10_000, **flt)
            assert [p["fideid"] for p in a[0]] == [p["fideid"] for p in b[0]] and a[1:] == b[1:]
