from datetime import date

from artemis.domain.imports import parse_csv


def test_parse_canonical_csv():
    text = "date,amount,description,currency,merchant,external_id\n"
    text += "2026-01-05,-42.50,Weekly shop,USD,Whole Foods,ext-1\n"
    text += "2026-01-06,1500.00,Paycheck,USD,Acme,ext-2\n"
    result = parse_csv(text)
    assert result.warnings == []
    assert len(result.rows) == 2
    assert result.rows[0].amount_minor == -4250
    assert result.rows[0].merchant == "Whole Foods"
    assert result.rows[0].external_id == "ext-1"
    assert result.rows[1].amount_minor == 150000


def test_parse_header_aliases():
    text = "Transaction Date,Value,Memo,Payee\n"
    text += "01/05/2026,-42.50,Weekly shop,Whole Foods\n"
    result = parse_csv(text)
    assert len(result.rows) == 1
    assert result.rows[0].posted_at == date(2026, 1, 5)
    assert result.rows[0].amount_minor == -4250
    assert result.rows[0].merchant == "Whole Foods"


def test_parse_debit_credit_columns():
    text = "date,debit,credit,description\n"
    text += "2026-01-05,42.50,,Coffee\n"
    text += "2026-01-06,,1500.00,Paycheck\n"
    result = parse_csv(text)
    assert result.rows[0].amount_minor == -4250
    assert result.rows[1].amount_minor == 150000


def test_parse_bad_rows_are_warnings():
    text = "date,amount,description\n"
    text += "not-a-date,-42.50,Bad\n"
    text += "2026-01-06,-10.00,Good\n"
    result = parse_csv(text)
    assert len(result.rows) == 1
    assert len(result.warnings) == 1
    assert "line 2" in result.warnings[0]


def test_parse_dayfirst():
    text = "date,amount\n05/01/2026,-42.50\n"
    us = parse_csv(text, dayfirst=False)
    uk = parse_csv(text, dayfirst=True)
    assert us.rows[0].posted_at == date(2026, 5, 1)
    assert uk.rows[0].posted_at == date(2026, 1, 5)


def test_missing_required_columns():
    result = parse_csv("foo,bar\n1,2\n")
    assert result.rows == []
    assert any("date" in w for w in result.warnings)


def test_synthesize_external_ids_is_stable():
    text = "date,amount,description,merchant\n"
    text += "2026-01-05,-42.50,Shop,Whole Foods\n"
    text += "2026-01-05,-42.50,Shop,Whole Foods\n"
    first = parse_csv(text, synthesize_external_ids=True)
    second = parse_csv(text, synthesize_external_ids=True)
    ids = [r.external_id for r in first.rows]
    assert ids[0] != ids[1]
    assert ids == [r.external_id for r in second.rows]
