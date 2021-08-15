"""Utility functions for simple-salesforce async calls"""
import httpx

from simple_salesforce.util import exception_handler


async def call_salesforce(
    url=None, method=None, async_client=None, headers=None, **kwargs
):
    """Utility method for performing HTTP call to Salesforce.

    Returns a `requests.result` object.
    """
    if not async_client:
        async_client = httpx.AsyncClient()

    additional_headers = kwargs.pop('additional_headers', dict())
    headers.update(additional_headers or dict())
    async with async_client as client:
        result = await client.request(method, url, headers=headers, **kwargs)

    if result.status_code >= 300:
        exception_handler(result)

    return result
