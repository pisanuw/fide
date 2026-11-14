from app.index import PlayerIndex
from scripts.uschess_top100 import CATEGORIES, birth_range, match_players
from tests.test_api import line


def test_birth_range():
    assert birth_range("Regular12", 2026) == (2012, 2015)
    assert birth_range("WomensBlitzUnder13AnyFed", 2026) == (2012, 9999)
    assert birth_range("Regular65Plus", 2026) == (0, 1962)
    assert birth_range("RegularOverall", 2026) == (0, 9999)
    assert len(CATEGORIES) == len(set(CATEGORIES)) == 160


def us(pid, first, last, country="USA", sex="M", born=(0, 9999)):
    return {"id": pid, "first": first, "last": last, "country": country, "sex": sex, "born": born}


def test_rules():
    ix = PlayerIndex([
        line(1, "Caruana, Fabiano", std=2800, born=1992),
        line(2, "Liu, Ethan", std=1900, born=2014),       # two US Ethan Lius: age decides
        line(3, "Liu, Ethan", std=1800, born=1990),
        line(4, "Lee, Aiden", "KOR", std=1500, born=2013),  # same name, other federation only
        line(5, "Choe, Matthew", std=1700, born=2010),      # US Chess says KOR, FIDE says USA
        line(6, "Smith, Anna", std=1600, born=2000),        # sex conflict
        line(7, "Old, Junior", std=1600, born=1950),        # single candidate, age does not fit
    ])
    players = {p["id"]: p for p in [
        us("12743305", "Fabiano", "Caruana"),
        us("30641803", "Ethan", "Liu", born=(2012, 2015)),
        us("30000001", "Aiden", "Lee", born=(2012, 2015)),
        us("30578086", "Matthew", "Choe", country="KOR"),
        us("30000002", "Anna", "Smith", sex="F"),
        us("30000003", "Junior", "Old", born=(2012, 2015)),
        us("30000004", "Nobody", "Here"),
    ]}
    r = match_players(players, ix)
    got = {row[0]: row[1] for row in r["rows"]}
    assert got == {"12743305": 1, "30641803": 2, "30578086": 5}
    # Lee: other federation; Smith: US Chess female, FIDE male; Old: born 1950, on an age-12 list
    assert {p["id"] for p, _ in r["no_fit"]} == {"30000001", "30000002", "30000003"}
    assert [p["id"] for p in r["unmatched"]] == ["30000004"]


def test_subset_names():
    ix = PlayerIndex([line(1, "Niemann, Hans Moke", std=2700, born=2003),
                      line(2, "Frank, Marty", std=2000, born=1962),
                      line(3, "Lee, Kim", std=1500), line(4, "Lee, Kim Ann", std=1500), line(5, "Lee, Kim Bo", std=1500)])
    r = match_players({"1": us("1", "Hans", "Niemann"), "2": us("2", "Marty C", "Frank", born=(0, 1962)),
                       "3": us("3", "Kim J", "Lee"), "4": us("4", "Kim", "Lee")}, ix)
    got = {row[0]: (row[1], row[5]) for row in r["rows"]}
    assert got["1"] == (1, "name-subset+fed+age") and got["2"] == (2, "name-subset+fed+age")
    assert got["4"] == (3, "name+fed+age")      # exact name wins; the subset pass never runs for it
    assert "3" not in got                       # "Kim J Lee" is neither subset nor superset of the FIDE names


def test_ambiguous_and_duplicate_fide():
    ix = PlayerIndex([line(1, "Zhu, Aiden", std=1900), line(2, "Zhu, Aiden", std=1800),
                      line(3, "Twin, Same", std=1700)])
    r = match_players({"9": us("9", "Aiden", "Zhu"), "10": us("10", "Same", "Twin"),
                       "11": us("11", "Same", "Twin")}, ix)
    assert [p["id"] for p, _ in r["ambiguous"]] == ["9"]
    assert r["rows"] == [] and r["dropped"] == 2  # one FIDE id claimed by two US Chess ids
