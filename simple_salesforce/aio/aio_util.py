"""Utility functions for simple-salesforce async calls"""

from functools import partial
from typing import Callable, NoReturn, Optional

import httpx

from simple_salesforce.exceptions import (
    SalesforceExpiredSession,
    SalesforceGeneralError,
    SalesforceMalformedRequest,
    SalesforceMoreThanOneRecord,
    SalesforceRefusedRequest,
    SalesforceResourceNotFound,
)
from simple_salesforce.util import Headers


def create_session_factory(
    proxies=None, timeout: Optional[int] = None
) -> Callable[[], httpx.AsyncClient]:
    """
    Convenience function for repeatedly returning the properly constructed
    AsyncClient.
    """
    if proxies and timeout:
        return partial(httpx.AsyncClient, proxies=proxies, timeout=timeout)
    if proxies:
        return partial(httpx.AsyncClient, proxies=proxies)
    if timeout:
        return partial(httpx.AsyncClient, timeout=timeout)

    return partial(httpx.AsyncClient)


async def call_salesforce(
    url: str = "",
    method: str = "GET",
    headers: Optional[Headers] = None,
    session_factory: Optional[Callable[[], httpx.AsyncClient]] = None,
    **kwargs
):
    """Utility method for performing HTTP call to Salesforce.

    Returns a `httpx.Response` object.
    """
    if session_factory:
        client = session_factory()
    else:
        client = httpx.AsyncClient()

    headers = headers or {}
    additional_headers = kwargs.pop("additional_headers", {})
    headers.update(additional_headers or {})

    async with client as session:
        result = await session.request(method, url, headers=headers, **kwargs)
    if result.status_code >= 300:
        exception_handler(result)

    return result


def exception_handler(result: httpx.Response, name: str = "") -> NoReturn:
    """Exception router. Determines which error to raise for bad results"""
    try:
        response_content = result.json()
    # pylint: disable=broad-except
    except Exception:
        response_content = result.text

    exc_map = {
        300: SalesforceMoreThanOneRecord,
        400: SalesforceMalformedRequest,
        401: SalesforceExpiredSession,
        403: SalesforceRefusedRequest,
        404: SalesforceResourceNotFound,
    }
    exc_cls = exc_map.get(result.status_code, SalesforceGeneralError)

    raise exc_cls(result.url, result.status_code, name, response_content)
