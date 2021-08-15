"""Simple-Salesforce Asyncio Package"""
# flake8: noqa

from .api import build_async_salesforce_client, AsyncSalesforce, SFType
from .bulk import SFBulkHandler
from .login import SalesforceLogin

# TODO
# $ rg -c requests
# login.py:4
# api.py:19
# util.py:1
# bulk.py:6
# tests/test_api.py:38
# tests/test_bulk.py:11
# tests/test_login.py:6
# api.py:40
# util.py:2
# messages.py:4
# login.py:14
# bulk.py:19
# metadata.py:12
# tests/test_api.py:83
# tests/test_login.py:26
# tests/test_util.py:3
# tests/test_bulk.py:28
# tests/__init__.py:2

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