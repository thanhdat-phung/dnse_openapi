from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from dnse_openapi.models import (
    NormalOrder,
    OCOOrder,
    ReplaceOrder,
    StopOrder,
    order_payload,
    to_vnd,
)


def test_normal_order_payload_uses_camel_case() -> None:
    order = NormalOrder(
        symbol="HPG",
        side="NB",
        order_type="LO",
        quantity=100,
        price=27500,
        loan_package_id=5757,
    )
    assert order_payload(order) == {
        "symbol": "HPG",
        "side": "NB",
        "orderType": "LO",
        "quantity": 100,
        "price": 27500,
        "loanPackageId": 5757,
    }
    assert "orderCategory" not in order_payload(order)


def test_normal_order_accepts_snake_case_arguments() -> None:
    order = NormalOrder(
        symbol="HPG",
        side="NS",
        order_type="LO",
        quantity=100,
        price=27500,
        loan_package_id=5757,
    )
    assert order.loan_package_id == 5757


def test_non_lo_order_must_send_zero_price() -> None:
    ato = NormalOrder(
        symbol="HPG",
        side="NB",
        order_type="ATO",
        quantity=100,
        price=0,
        loan_package_id=5757,
    )
    assert order_payload(ato)["price"] == 0

    with pytest.raises(ValidationError, match="price must be 0"):
        NormalOrder(
            symbol="HPG",
            side="NB",
            order_type="ATO",
            quantity=100,
            price=27500,
            loan_package_id=5757,
        )


def test_lo_order_requires_positive_price() -> None:
    with pytest.raises(ValidationError, match="price must be > 0"):
        NormalOrder(
            symbol="HPG",
            side="NB",
            order_type="LO",
            quantity=100,
            price=0,
            loan_package_id=5757,
        )


def test_quantity_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        NormalOrder(
            symbol="HPG",
            side="NB",
            order_type="LO",
            quantity=0,
            price=27500,
            loan_package_id=5757,
        )


def test_stop_order_payload() -> None:
    order = StopOrder(
        symbol="41I1G8000",
        side="NS",
        order_type="LO",
        quantity=3,
        price=1900,
        loan_package_id=2278,
        stop_price=1700,
        condition_operator=">=",
        duration_date_time=datetime(
            2026, 8, 20, 7, 30, tzinfo=timezone(timedelta(hours=7))
        ),
    )
    assert order_payload(order) == {
        "symbol": "41I1G8000",
        "side": "NS",
        "orderType": "LO",
        "quantity": 3,
        "price": 1900,
        "loanPackageId": 2278,
        "stopPrice": 1700,
        "conditionOperator": ">=",
        "durationType": "GTD",
        "durationDateTime": "2026-08-20T07:30:00.000+07:00",
    }


def test_stop_order_requires_timezone_aware_expiry() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        StopOrder(
            symbol="HPG",
            side="NS",
            quantity=100,
            price=27500,
            loan_package_id=5757,
            stop_price=27000,
            condition_operator="<=",
            duration_date_time=datetime(2026, 8, 20, 7, 30),
        )


def test_stop_order_mtl_requires_zero_price() -> None:
    with pytest.raises(ValidationError, match="price must be 0"):
        StopOrder(
            symbol="HPG",
            side="NS",
            order_type="MTL",
            quantity=100,
            price=27500,
            loan_package_id=5757,
            stop_price=27000,
            condition_operator="<=",
            duration_date_time=datetime(2026, 8, 20, 7, 30, tzinfo=timezone.utc),
        )


def test_oco_order_defaults() -> None:
    order = OCOOrder(
        symbol="41I1G8000",
        side="NB",
        quantity=3,
        price=1990,
        loan_package_id=2278,
        stop_price=2000,
        stop_order_price=2005,
    )
    payload = order_payload(order)
    assert payload["orderType"] == "LO"
    assert payload["durationType"] == "DAY"
    assert payload["stopOrderPrice"] == 2005


def test_replace_requires_a_field() -> None:
    with pytest.raises(ValidationError, match="at least one"):
        ReplaceOrder()
    assert ReplaceOrder(price=12500).model_dump(exclude_none=True) == {"price": 12500}


def test_to_vnd_converts_thousands() -> None:
    assert to_vnd(27.5) == 27500
    assert to_vnd(100) == 100000
