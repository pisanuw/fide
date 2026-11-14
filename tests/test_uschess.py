import pytest
from fastapi.testclient import TestClient

from app import main
from app.index import PlayerIndex, load_uschess_map
from tests.test_api import line

LINES = [
    line(12743305, "Shared, Fide", std=2000),          # FIDE id equal to another player's US Chess id
    line(2020009, "Caruana, Fabiano", std=2800),
    line(30922453, "Aafjes, Marc", std=1700),
    line(30900001, "Prefix, Fide", std=1600),
    line(5000017, "Nomap, Player", std=2500, fed="NOR"),
]
USCHESS = {2020009: 12743305, 30922453: 12345678, 30900001: 30911111}


@pytest.fixture()
def ix():
    return PlayerIndex(LINES, uschess=USCHESS)


def ids(rs):
    return [r["fideid"] for r in rs]


def test_record_has_uschess_id(ix):
    assert ix.get_fide(2020009)["uschess_id"] == 12743305
    assert ix.get_fide(5000017)["uschess_id"] is None
    assert ix.get_uschess(12345678)["name"] == "Aafjes, Marc"
    assert ix.get_uschess(99999999) is None


def test_exact_uschess_and_overlapping_fide_id(ix):
    # 12743305 is Shared's FIDE id and Caruana's US Chess id: both, best rating first
    found, total, exact = ix.find("12743305", 5)
    assert ids(found) == [2020009, 12743305] and (total, exact) == (2, True)


def test_uschess_prefix(ix):
    assert ids(ix.find("123456", 5)[0]) == [30922453]
    # "309" matches FIDE ids 30922453 and 30900001, and US Chess id 30911111 (the same 30900001): no duplicates
    found, total, _ = ix.find("309", 5)
    assert ids(found) == [30922453, 30900001] and total == 2
    assert ix.find("12", 5) == ([], 0, True)  # 1-2 digits: exact only


def test_uschess_with_filters(ix):
    assert ix.find("12743305", 5, fed="NOR")[0] == []
    assert ids(ix.find("12743305", 5, born=1990)[0]) == [2020009, 12743305]


def test_load_map(tmp_path):
    p = tmp_path / "m.tsv"
    p.write_text("uschess_id\tfide_id\tuschess_name\n12743305\t2020009\tCaruana, Fabiano\nbad\t1\tx\n")
    assert load_uschess_map(str(p)) == {2020009: 12743305}
    assert load_uschess_map(str(tmp_path / "missing.tsv")) == {}


@pytest.fixture()
def client(ix):
    main.state["index"] = ix
    main._hits.clear()
    with TestClient(main.app) as c:
        yield c


def test_api_uschess(client):
    assert client.get("/api/players/uschess/12345678").json()[0]["fideid"] == 30922453
    assert client.get("/api/players/uschess/1").status_code == 404
    r = client.get("/api/players", params={"q": "12743305"})
    assert [p["uschess_id"] for p in r.json()] == [12743305, None] and r.headers["x-total-count"] == "2"
    assert list(r.json()[0])[-1] == "uschess_id"  # new key is last; earlier keys keep their order
    txt = client.get("/api/players", params={"q": "nomap", "format": "txt"}).text.splitlines()
    assert txt[0].endswith("\tuschess_id") and txt[1].endswith("\t")  # None -> empty, not "None"
    xml = client.get("/api/players", params={"q": "nomap", "format": "xml"}).text
    assert "<uschess_id></uschess_id>" in xml
