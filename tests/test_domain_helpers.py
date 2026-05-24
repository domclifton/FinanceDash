"""Smoke tests for domain-specific helper parsing/normalisation."""


def test_debt_type_accepts_known_value(app_module):
    assert app_module.normalise_debt_type("Credit Card") == "Credit Card"


def test_debt_type_unknown_falls_back_to_other(app_module):
    assert app_module.normalise_debt_type("Store Card") == "Other"
    assert app_module.normalise_debt_type("") == "Other"


def test_trading212_gbx_values_convert_to_gbp(app_module):
    assert app_module.normalise_trading212_money(1234, "GBX") == 12.34


def test_trading212_gbp_values_stay_as_pounds(app_module):
    assert app_module.normalise_trading212_money(1234, "GBP") == 1234


def test_trading212_invalid_money_returns_zero(app_module):
    assert app_module.normalise_trading212_money("not-a-number", "GBP") == 0.0


def test_payoff_months_zero_apr_uses_ceiling_division():
    from services.debts import payoff_months_with_interest

    assert payoff_months_with_interest(1000, 0, 100) == 10
    assert payoff_months_with_interest(1000.01, 0, 100) == 11


def test_payoff_months_with_interest_extends_payoff_time():
    from services.debts import payoff_months_with_interest

    assert payoff_months_with_interest(3000, 28, 80) > 38


def test_payoff_months_returns_none_when_payment_does_not_cover_interest():
    from services.debts import payoff_months_with_interest

    assert payoff_months_with_interest(3000, 28, 60) is None


def test_safe_float_shared_helper():
    from utils import safe_float

    assert safe_float("12.50") == 12.5
    assert safe_float("") == 0.0
    assert safe_float("bad", default=3) == 3.0
