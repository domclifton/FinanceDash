"""Smoke tests for small calculation/formatting helpers."""


def test_format_money_basic(app_module):
    assert app_module.format_money(1234.5) == "£1,234.50"


def test_format_money_negative(app_module):
    assert app_module.format_money(-500) == "-£500.00"


def test_format_money_zero(app_module):
    assert app_module.format_money(0) == "£0.00"


def test_compound_projection_basic_growth(app_module):
    result = app_module.compound_projection(10000, 5, 10, 0)
    assert 16200 < result["future_value"] < 16600
    assert result["points"][-1]["year_label"] == "Year 10"


def test_nice_axis_max_rounds_with_headroom(app_module):
    assert app_module._nice_axis_max(0) == 1.0
    assert app_module._nice_axis_max(1100) == 2000
    assert app_module._nice_axis_max(9500) == 20000
