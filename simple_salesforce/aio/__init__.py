"""Simple-Salesforce Asyncio Package"""
# flake8: noqa

from .api import build_async_salesforce_client, AsyncSalesforce, AsyncSFType
from .bulk import AsyncSFBulkHandler
from .login import AsyncSalesforceLogin

# TODO
# import asyncio
# from simple_salesforce.aio import *
# import os
# loop = asyncio.get_event_loop()
# username = os.environ["DIRECT_APP_SF_CLIENT_USERNAME"]
# consumer_key = os.environ["DIRECT_APP_SF_CLIENT_CONSUMER_KEY"]
# sf_priv_keyfile = os.environ["DIRECT_APP_SF_CLIENT_PRIVATE_KEY"]
# env = {'domain': "test"}
# client = loop.run_until_complete(build_async_salesforce_client(
#     username=username, consumer_key=consumer_key,privatekey_file=sf_priv_keyfile, domain="test")
# )