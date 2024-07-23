"""Tests for simple-salesforce aio utility functions"""
import httpx

import pytest

from simple_salesforce.exceptions import (
    SalesforceExpiredSession,
    SalesforceMalformedRequest,
    SalesforceMoreThanOneRecord,
    SalesforceRefusedRequest,
    SalesforceResourceNotFound,
)
from simple_salesforce.aio.aio_util import call_salesforce



async def test_call_salesforce_happy_path(httpx_mock):
    """Test happy path responses: <= 300"""
    httpx_mock.add_response(
        method="GET", url="https://www.example.com", status_code=200
    )
    # no exceptions
    result = await call_salesforce(
            method="GET", url="https://www.example.com"
    )
    assert isinstance(result, httpx.Response) and result.status_code == 200



@pytest.mark.parametrize(
    "status_code,exception_class",
    (
        (300, SalesforceMoreThanOneRecord),
        (400, SalesforceMalformedRequest),
        (401, SalesforceExpiredSession),
        (403, SalesforceRefusedRequest),
        (404, SalesforceResourceNotFound),
    ),
)
async def test_call_salesforce_exceptions(
    status_code, exception_class, httpx_mock
):
    """Test exception-handling responses: => 300"""

    httpx_mock.add_response(
        method="GET", url="https://www.example.com", status_code=status_code
    )

    with pytest.raises(exception_class):
        await call_salesforce(
            method="GET", url="https://www.example.com",
        )
