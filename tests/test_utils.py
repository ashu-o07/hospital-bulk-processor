import pytest
from fastapi import HTTPException
from main import _validate_and_parse_csv


def test_parse_basic():
    data = "A,Addr,123\nB,Addr2,\n"
    rows = _validate_and_parse_csv(data.encode())
    assert len(rows) == 2
    assert rows[0]["name"] == "A"


def test_parse_missing_fields():
    with pytest.raises(HTTPException):
        _validate_and_parse_csv("OnlyName\n".encode())


def test_parse_too_many_rows():
    lines = "\n".join([f"Name{i},Addr{i}," for i in range(21)])
    with pytest.raises(HTTPException):
        _validate_and_parse_csv(lines.encode())
