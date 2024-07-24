# Async Simple Salesforce

This is an **async fork** of the library [simple-salesforce](https://github.com/simple-salesforce/simple-salesforce). It is considered **alpha** software.

This fork is available on PyPI and can be installed like this:

```sh
$ pip install "async-simple-salesforce==1.12.6a1"

```

## Versions

Versioning for this library tracks the upstream version; i.e., when a new version of upstream has been published, it will be integrated into this codebase and released under the *same* version identifier, with one notable difference: we add *alpha* or *beta* identifiers to make it more obvious that this fork has not been around as long as upstream and that it has also not seen the same wide-scale usage that upstream has.

For example, when changes from upstream version `1.12.4` have been integrated into this library, a new version of this library will be published as `1.12.4a1`. Further changes under the same version will increment the alpha version identifier.

## How to Use

This library attempts to offer the *same API* as `simple-salesforce` inside an `aio` subpackage.

For instance, here's how to create and use an async Salesforce client:

```python

import asyncio
import datetime

from simple_salesforce.aio import build_async_salesforce_client, AsyncSalesforce


async def create_client(username, consumer_key, private_key) -> AsyncSalesforce:
    # build_async_salesforce_client accepts all args of simple-salesforce Login
    return await build_async_salesforce_client(
            username=username,
            consumer_key=consumer_key,
            privatekey_file=private_key,
            request_timeout_seconds=60 * 2,
        )

async def update_contact(sf_client):
    end = datetime.datetime.now(pytz.UTC) # we need to use UTC as salesforce API requires this
    await sf_client.Contact.updated(end - datetime.timedelta(days=10), end)


async def run_query(sf_client, opportunity_name: str):
    query = (
        f"SELECT Id,StageName from Opportunity where "
        f"Name='{opportunity_name}'"
    )
    return await sf_client.query_all(search)
```

You can typically call *any* method available on the synchronous `Salesforce` object as an async method with an `await` added.

See upstream docs continued below.