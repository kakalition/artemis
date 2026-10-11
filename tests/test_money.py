from decimal import Decimal

import pytest

from artemis.domain.money import (
    decimal_to_minor,
    format_minor,
    minor_exponent,
    minor_to_decimal,
    parse_amount,
)


def test_minor_exponent():
    assert minor_exponent("USD") == 2
    assert minor_exponent("usd") == 2
    assert minor_exponent("JPY") == 0
    assert minor_exponent("KWD") == 3
    assert minor_exponent("ZZZ") == 2


def test_decimal_to_minor():
    assert decimal_to_minor("42.50") == 4250
    assert decimal_to_minor(Decimal("42.5")) == 4250
    assert decimal_to_minor(42) == 4200
    assert decimal_to_minor("42.55", "JPY") == 43  # banker's rounding
    assert decimal_to_minor("-3.005") == -300
    assert isinstance(decimal_to_minor("1.23"), int)


def test_minor_to_decimal():
    assert minor_to_decimal(4250) == Decimal("42.50")
    assert minor_to_decimal(4250).as_tuple().exponent == -2


def test_parse_amount_basic():
    assert parse_amount("42.50") == 4250
    assert parse_amount("$42.50") == 4250
    assert parse_amount("$1,234.56") == 123456
    assert parse_amount("42") == 4200
    assert parse_amount("  7.5  ") == 750


def test_parse_amount_signs():
    assert parse_amount("-42.00") == -4200
    assert parse_amount("(42.00)") == -4200
    assert parse_amount("+42.00") == 4200


def test_parse_amount_currency():
    assert parse_amount("42 USD") == 4200
    assert parse_amount("USD 42") == 4200
    assert parse_amount("100 JPY") == 100
    assert parse_amount("10 €") == 1000


@pytest.mark.parametrize("bad", ["", "abc", "$", "1.2.3", None])
def test_parse_amount_invalid(bad):
    with pytest.raises(ValueError):
        parse_amount(bad)


def test_format_minor():
    assert format_minor(123456) == "$1,234.56"
    assert format_minor(-4200) == "-$42.00"
    assert format_minor(100) == "$1.00"
    assert format_minor(100, "USD", with_symbol=False) == "1.00 USD"
    assert format_minor(100, "JPY") == "¥100"
    assert format_minor(1234, "ZZZ") == "12.34 ZZZ"


def test_no_float_on_monetary_path():
    with pytest.raises(TypeError):
        decimal_to_minor(1.5)  # type: ignore[arg-type]
