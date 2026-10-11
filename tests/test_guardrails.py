from artemis.guardrails import is_loopback, warn_if_exposed


def test_is_loopback():
    assert is_loopback("127.0.0.1") is True
    assert is_loopback("::1") is True
    assert is_loopback("localhost") is True
    assert is_loopback("0.0.0.0") is False
    assert is_loopback("10.0.0.5") is False
    assert is_loopback(None) is True


def test_warn_if_exposed(capsys):
    warn_if_exposed("0.0.0.0", "the test server")
    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "the test server" in err

    warn_if_exposed("127.0.0.1", "the test server")
    assert capsys.readouterr().err == ""
