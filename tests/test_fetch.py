import zipfile

import pytest

from scripts import fetch_fide
from tests.test_api import LINES

HEADER = ("ID Number      Name                                                         Fed Sex Tit  WTit OTit"
          "           FOA SRtng SGm SK RRtng RGm Rk BRtng BGm BK B-day Flag")


def test_header_matches_app_columns():
    fetch_fide.check_header(HEADER)


def test_shifted_header_is_rejected():
    with pytest.raises(ValueError, match="column layout changed"):
        fetch_fide.check_header(HEADER.replace("Fed Sex", "Fed  Sex"))


def make_zip(path, header, when=(2026, 12, 1, 22, 3, 0)):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(zipfile.ZipInfo("players_list_foa.txt", when), header + "\r\n" + "\r\n".join(LINES) + "\r\n")


def test_validate_txt_month_and_minimum(tmp_path, monkeypatch):
    p = tmp_path / "players_list.zip"
    make_zip(p, HEADER)
    monkeypatch.setattr(fetch_fide, "MIN_RATED", 1)
    assert fetch_fide.validate_txt(p) == ("202612", 6)
    monkeypatch.setattr(fetch_fide, "MIN_RATED", 7)
    with pytest.raises(ValueError, match="rated players"):
        fetch_fide.validate_txt(p)
