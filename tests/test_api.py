import pytest
from fastapi.testclient import TestClient

from app import main
from app.index import PlayerIndex


def line(fid, name, fed="USA", std=0, rapid=0, blitz=0, flag=""):
    s = f"{fid:<15}{name:<61}{fed:<4}{'M':<4}{'':<5}{'':<5}{'':<15}{'':<4}"
    s += f"{std:>6}{0:>4}{40:>3}{rapid:>6}{0:>4}{0:>3}{blitz:>6}{0:>4}{0:>3}{1990:>6}{flag}"
    return s


LINES = [
    line(1, "Pisan, Yusuf", std=1900),
    line(2, "Pisani, Marco", "ITA", std=2100),
    line(3, "Apisan, Zed", std=1500),
    line(4, "Müller, José", "GER", std=2200),
    line(5, "Nobody, Unrated"),
    line(7, "Pisan, Yusuf Junior", std=2300),
    line(6, "O'Brien & Sons, <Al>", std=1700),
]


@pytest.fixture()
def client():
    main.state["index"] = PlayerIndex(LINES)
    main._hits.clear()
    with TestClient(main.app) as c:
        yield c


def names(r):
    return [p["name"] for p in r.json()]


def test_prefix_ranked_by_rating_then_substring_fallback(client):
    assert names(client.get("/api/players", params={"q": "pisan"})) == [
        "Pisan, Yusuf Junior", "Pisani, Marco", "Pisan, Yusuf", "Apisan, Zed"]


def test_exact_name_first_any_order(client):
    assert names(client.get("/api/players", params={"q": "pisan yusuf"}))[:2] == [
        "Pisan, Yusuf", "Pisan, Yusuf Junior"]
    assert names(client.get("/api/players", params={"q": "yusuf, pisan"}))[0] == "Pisan, Yusuf"


def test_multi_token_any_order_and_accents(client):
    assert names(client.get("/api/players", params={"q": "jose mul"})) == ["Müller, José"]
    assert names(client.get("/api/players", params={"q": "yusuf pis"})) == ["Pisan, Yusuf Junior", "Pisan, Yusuf"]


def test_limit_and_unrated_excluded(client):
    assert len(client.get("/api/players", params={"q": "pisan", "limit": 1}).json()) == 1
    assert client.get("/api/players", params={"q": "nobody"}).json() == []
    assert client.get("/api/players", params={"q": "pisan", "limit": 6}).status_code == 422


def test_fide_id(client):
    assert names(client.get("/api/players", params={"q": "2"})) == ["Pisani, Marco"]
    assert client.get("/api/players/fide/4").json()[0]["fed"] == "GER"
    assert client.get("/api/players/fide/999").status_code == 404


def test_fide_id_prefix(client):
    main.state["index"] = PlayerIndex([line(1503014, "Carlsen, Magnus", std=2800),
                                       line(150301, "Exact, Id", std=1000),
                                       line(15030140, "Longer, Id", std=2000),
                                       line(1503099, "Other, Id", std=1500),
                                       line(1604000, "Not, Match", std=2900)])
    r = client.get("/api/players", params={"q": "150301"})
    assert names(r) == ["Exact, Id", "Carlsen, Magnus", "Longer, Id"]  # exact, then by rating
    assert names(client.get("/api/players", params={"q": "1503", "limit": 2})) == ["Carlsen, Magnus", "Longer, Id"]
    assert names(client.get("/api/players", params={"q": "15"})) == []  # too short for prefix


def test_total_count_header(client):
    r = client.get("/api/players", params={"q": "pisan", "limit": 2})
    assert len(r.json()) == 2
    assert r.headers["x-total-count"] == "4" and r.headers["x-total-count-exact"] == "true"
    r = client.get("/api/players", params={"q": "zzzz"})
    assert r.json() == [] and r.headers["x-total-count"] == "0"


def test_total_count_cap_and_ids():
    ix = PlayerIndex([line(i, f"Pisan, Player{i}", std=1000 + i) for i in range(100, 130)])
    assert ix.count("pisan") == (30, True)
    assert ix.count("pisan", cap=10) == (10, False)
    assert ix.count("player12 pisan") == (10, True)  # 120-129
    assert ix.count("11") == (0, True)  # 1-2 digits: exact id only
    assert ix.count("12") == (0, True)
    assert ix.count("125") == (1, True)
    assert ix.count("") == (0, True) and ix.count("p") == (0, True)


def test_formats_and_download(client):
    r = client.get("/api/players", params={"q": "pisan", "format": "xml", "download": 1})
    assert r.headers["content-type"].startswith("application/xml")
    assert "attachment" in r.headers["content-disposition"] and "<fideid>2</fideid>" in r.text
    r = client.get("/api/players", params={"q": "brien", "format": "xml"})
    assert "&amp;" in r.text and "&lt;Al&gt;" in r.text
    r = client.get("/api/players", params={"q": "pisan", "format": "txt"})
    assert r.text.splitlines()[0].startswith("fideid\tname") and len(r.text.splitlines()) == 5
    assert client.get("/api/players", params={"q": "x", "format": "csv"}).status_code == 422


def test_rate_limit(client, monkeypatch):
    monkeypatch.setattr(main, "RATE_LIMIT", 3)
    codes = [client.get("/api/players", params={"q": "pisan"}).status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    other = client.get("/api/players", params={"q": "pisan"}, headers={"x-forwarded-for": "9.9.9.9"})
    assert other.status_code == 200


def test_home(client):
    assert "<title>FIDE lookup" in client.get("/").text
