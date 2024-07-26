"""Async Classes for interacting with Salesforce Bulk API """

import asyncio
from collections import OrderedDict
from functools import partial
import json
import logging
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Union

import httpx
from more_itertools import chunked

from simple_salesforce.exceptions import SalesforceGeneralError
from simple_salesforce.util import (
    BulkDataAny,
    BulkDataStr,
    Headers,
    Proxies,
)
from .aio_util import call_salesforce, create_session_factory, alist_from_generator


# pylint: disable=invalid-name
logger = logging.getLogger(__name__)

BATCH_FINISH_STATES = set(("Completed", "Failed", "NotProcessed"))


class AsyncSFBulkHandler:
    """Bulk API request handler
    Intermediate class which allows us to use commands,
     such as 'sf.bulk.Contacts.create(...)'
    This is really just a middle layer, whose sole purpose is
    to allow the above syntax
    """

    def __init__(
        self,
        session_id: str,
        bulk_url: str,
        proxies: Optional[Proxies] = None,
        session_factory: Optional[Callable[[], httpx.AsyncClient]] = None,
    ):
        """Initialize the instance with the given parameters.

        Arguments:

        * session_id -- the session ID for authenticating to Salesforce
        * bulk_url -- API endpoint set in Salesforce instance
        * proxies -- the optional map of scheme to proxy server
        * session_factory -- Function to return a custom httpx session (AsyncClient).
                             This enables the use of httpx Session features not otherwise
                             exposed by simple_salesforce.
        """
        self.session_id = session_id
        self.bulk_url = bulk_url
        # don't wipe out original proxies with None
        if not session_factory:
            session_factory = create_session_factory(proxies=proxies)
        self.session_factory = session_factory

        # Define these headers separate from Salesforce class,
        # as bulk uses a slightly different format
        self.headers = {
            "Content-Type": "application/json",
            "X-SFDC-Session": self.session_id,
            "X-PrettyPrint": "1",
        }

    def __getattr__(self, name: str) -> "AsyncSFBulkType":
        return AsyncSFBulkType(
            object_name=name,
            bulk_url=self.bulk_url,
            headers=self.headers,
            session_factory=self.session_factory,
        )


class AsyncSFBulkType:
    """Interface to Bulk/Async API functions"""

    def __init__(
        self,
        object_name: str,
        bulk_url: str,
        headers: Headers,
        session_factory: Callable[[], httpx.AsyncClient],
    ):
        """Initialize the instance with the given parameters.

        Arguments:

        * object_name -- the name of the type of SObject this represents,
                         e.g. `Lead` or `Contact`
        * bulk_url -- API endpoint set in Salesforce instance
        * headers -- bulk API headers
        * session_factory -- Function to return a custom httpx session (AsyncClient).
                             This enables the use of httpx Session features not otherwise
                             exposed by simple_salesforce.
        """
        self.object_name = object_name
        self.bulk_url = bulk_url
        self.session_factory = session_factory
        self.headers = headers

    async def _create_job(
        self, operation: str, use_serial: bool, external_id_field: Optional[str] = None
    ) -> Any:
        """Create a bulk job

        Arguments:

        * operation -- Bulk operation to be performed by job
        * use_serial -- Process batches in order
        * external_id_field -- unique identifier field for upsert operations
        """

        payload = {
            "operation": operation,
            "object": self.object_name,
            "concurrencyMode": 1 if use_serial else 0,
            "contentType": "JSON",
        }

        if operation == "upsert":
            payload["externalIdFieldName"] = external_id_field

        url = f"{self.bulk_url}job"

        result = await call_salesforce(
            url=url,
            method="POST",
            session_factory=self.session_factory,
            headers=self.headers,
            content=json.dumps(payload, allow_nan=False),
        )
        return result.json(object_pairs_hook=OrderedDict)

    async def _close_job(self, job_id: str) -> Any:
        """Close a bulk job"""
        payload = {"state": "Closed"}

        url = f"{self.bulk_url}job/{job_id}"

        result = await call_salesforce(
            url=url,
            method="POST",
            session_factory=self.session_factory,
            headers=self.headers,
            content=json.dumps(payload, allow_nan=False),
        )
        return result.json(object_pairs_hook=OrderedDict)

    async def _get_job(self, job_id: str) -> Any:
        """Get an existing job to check the status"""
        url = f"{self.bulk_url}job/{job_id}"

        result = await call_salesforce(
            url=url,
            method="GET",
            session_factory=self.session_factory,
            headers=self.headers,
        )
        return result.json(object_pairs_hook=OrderedDict)

    async def _add_batch(self, job_id: str, data: BulkDataAny, operation: str) -> Any:
        """Add a set of data as a batch to an existing job
        Separating this out in case of later
        implementations involving multiple batches
        """

        url = f"{self.bulk_url}job/{job_id}/batch"

        content: str | BulkDataAny = data
        if operation not in ("query", "queryAll"):
            content = json.dumps(data, allow_nan=False)

        result = await call_salesforce(
            url=url,
            method="POST",
            session_factory=self.session_factory,
            headers=self.headers,
            content=content,
        )
        return result.json(object_pairs_hook=OrderedDict)

    async def _get_batch(self, job_id: str, batch_id: str) -> Any:
        """Get an existing batch to check the status"""

        url = f"{self.bulk_url}job/{job_id}/batch/{batch_id}"

        result = await call_salesforce(
            url=url,
            method="GET",
            session_factory=self.session_factory,
            headers=self.headers,
        )
        return result.json(object_pairs_hook=OrderedDict)

    async def _get_batch_results(
        self, job_id: str, batch_id: str, operation: str
    ) -> AsyncIterator[Any]:
        """retrieve a set of results from a completed job"""

        url = f"{self.bulk_url}job/{job_id}/batch/{batch_id}/result"

        result = await call_salesforce(
            url=url,
            method="GET",
            session_factory=self.session_factory,
            headers=self.headers,
        )

        if operation in ("query", "queryAll"):
            for batch_result in result.json():
                url_query_results = f"{url}/{batch_result}"
                batch_query_result = await call_salesforce(
                    url=url_query_results,
                    method="GET",
                    session_factory=self.session_factory,
                    headers=self.headers,
                )
                yield batch_query_result.json()
        else:
            yield result.json()

    async def _add_autosized_batches(
        self, data: BulkDataAny, operation: str, job: str
    ) -> List[Any]:
        """
        Auto-create batches that respect bulk api V1 limits.

        bulk v1 api has following limits
        number of records <= 10000
        AND
        file_size_limit <= 10MB
        AND
        number_of_character_limit <= 10000000

        Documentation on limits can be found at:
        https://developer.salesforce.com/docs/atlas.en-us.salesforce_app_limits_cheatsheet.meta/salesforce_app_limits_cheatsheet/salesforce_app_limits_platform_bulkapi.htm#ingest_jobs

        Our JSON serialization uses the default `ensure_ascii=True`, so the
        character and byte lengths will be the same. Therefore we only need
        to adhere to a single length limit of 10,000,000 characters.

        TODO: In future when simple-salesforce supports bulk api V2
        we should detect api version and set max file size accordingly. V2
        increases file size limit to 150MB

        TODO: support for the following limits have not been added since these
        are record / field level limits and not chunk level limits:
        * Maximum number of fields in a record: 5,000
        * Maximum number of characters in a record: 400,000
        * Maximum number of characters in a field: 131,072
        """
        record_limit = 10_000
        char_limit = 10_000_000

        batches = []
        last_break = 0
        record_count, char_count = 0, 0
        for i, record in enumerate(data):
            # 2 is added to account for the enclosing `[]`
            # and the separator `, ` between records.
            additional_chars = len(json.dumps(record, default=str)) + 2
            if any(
                [
                    char_count + additional_chars > char_limit,
                    record_count == record_limit,
                ]
            ):
                batches.append(data[last_break:i])
                last_break = i
                record_count, char_count = 0, 0
            char_count += additional_chars
            record_count += 1
        if last_break < len(data) - 1:
            batches.append(data[last_break:])

        futures = [
            self._add_batch(job_id=job, data=i, operation=operation) for i in batches
        ]
        return await asyncio.gather(*futures)

    async def worker(
        self,
        batch: Dict[str, Any],
        operation: str,
        wait: int = 5,
        bypass_results: bool = False,
    ) -> List[Dict[str, Any]]:
        """Gets batches from concurrent worker threads.
        self._bulk_operation passes batch jobs.
        The worker function checks each batch job waiting for it complete
        and appends the results.
        """
        if not bypass_results:
            batch_status = await self._get_batch(
                job_id=batch["jobId"], batch_id=batch["id"]
            )

            while batch_status["state"] not in BATCH_FINISH_STATES:
                await asyncio.sleep(wait)
                batch_status = await self._get_batch(
                    job_id=batch["jobId"], batch_id=batch["id"]
                )

            batch_results = []
            async for batch_res in self._get_batch_results(
                job_id=batch["jobId"], batch_id=batch["id"], operation=operation
            ):
                batch_results.append(batch_res)
            result = batch_results
        else:
            result = [{"bypass_results": bypass_results, "job_id": batch["jobId"]}]
        return result

    # pylint: disable=R0913
    async def _bulk_operation(
        self,
        operation: str,
        data: BulkDataAny,
        use_serial: bool = False,
        external_id_field: Optional[str] = None,
        batch_size: Union[int, str] = 10000,
        concurrency: int = 5,
        wait: int = 5,
        bypass_results: bool = False,
    ) -> AsyncIterator[Any]:
        """String together helper functions to create a complete
        end-to-end bulk API request
        Arguments:
        * operation -- Bulk operation to be performed by job
        * data -- list of dict to be passed as a batch
        * use_serial -- Process batches in serial mode
        * external_id_field -- unique identifier field for upsert operations
        * wait -- seconds to sleep between checking batch status
        * batch_size -- number of records to assign for each batch in the job
                        or "auto"
        * concurrency -- number of results to process concurrently
        """
        # check for batch size type since now it accepts both integers
        # & the string `auto`
        if not (isinstance(batch_size, int) or batch_size == "auto"):
            raise ValueError("batch size should be auto or an integer")

        if operation not in ("query", "queryAll"):
            if not data:
                raise ValueError(f"data should not be empty for {operation}")

            # Checks to prevent batch limit
            if batch_size != "auto":
                batch_size = min(batch_size, len(data), 10000)

            job = await self._create_job(
                operation=operation,
                use_serial=use_serial,
                external_id_field=external_id_field,
            )
            if batch_size == "auto":
                batches = await self._add_autosized_batches(
                    data=data, operation=operation, job=job["id"]
                )
            else:
                batches = [
                    self._add_batch(job_id=job["id"], data=i, operation=operation)
                    for i in [
                        data[i * batch_size : (i + 1) * batch_size]
                        for i in range((len(data) // batch_size + 1))
                    ]
                    if i
                ]

            batch_results = await asyncio.gather(*batches)
            worker = partial(
                self.worker,
                operation=operation,
                wait=wait,
                bypass_results=bypass_results,
            )
            list_of_tasks = map(worker, batch_results)
            chunk_results = chunked(list_of_tasks, concurrency)
            for chunk in chunk_results:
                list_of_results = await asyncio.gather(*chunk)
                for sublist in list_of_results:
                    for i in sublist:
                        if not bypass_results:
                            for x in i:
                                yield x
                        else:
                            for k, v in i.items():
                                yield {k: v}

            await self._close_job(job_id=job["id"])

        elif operation in ("query", "queryAll"):
            job = await self._create_job(
                operation=operation,
                use_serial=use_serial,
                external_id_field=external_id_field,
            )

            batch = await self._add_batch(
                job_id=job["id"], data=data, operation=operation
            )
            await self._close_job(job_id=job["id"])

            batch_status = await self._get_batch(
                job_id=batch["jobId"], batch_id=batch["id"]
            )
            while batch_status["state"] not in BATCH_FINISH_STATES:
                await asyncio.sleep(wait)
                batch_status = await self._get_batch(
                    job_id=batch["jobId"], batch_id=batch["id"]
                )
            if batch_status["state"] == "Failed":
                raise SalesforceGeneralError(
                    "",
                    batch_status["state"],
                    batch_status["jobId"],
                    batch_status["stateMessage"],
                )

            async for res in self._get_batch_results(
                job_id=batch["jobId"], batch_id=batch["id"], operation=operation
            ):
                yield res


    # _bulk_operation wrappers to expose supported Salesforce bulk operations
    async def delete(
        self,
        data: BulkDataStr,
        batch_size: int = 10000,
        use_serial: bool = False,
        wait: int = 5,
        bypass_results: bool = False,
    ) -> AsyncIterator[Any]:
        """soft delete records

        Data is batched by 10,000 records by default. To pick a lower size
        pass smaller integer to `batch_size`. to let simple-salesforce pick
        the appropriate limit dynamically, enter `batch_size='auto'`
        """
        return self._bulk_operation(
            use_serial=use_serial,
            operation="delete",
            data=data,
            batch_size=batch_size,
            wait=wait,
            bypass_results=bypass_results,
        )

    async def insert(
        self,
        data: BulkDataAny,
        batch_size: int = 10000,
        use_serial: bool = False,
        wait: int = 5,
        bypass_results: bool = False,
    ) -> AsyncIterator[Any]:
        """insert records

        Data is batched by 10,000 records by default. To pick a lower size
        pass smaller integer to `batch_size`. to let simple-salesforce pick
        the appropriate limit dynamically, enter `batch_size='auto'`
        """
        return self._bulk_operation(
            use_serial=use_serial,
            operation="insert",
            data=data,
            batch_size=batch_size,
            wait=wait,
            bypass_results=bypass_results,
        )

    async def upsert(
        self,
        data: BulkDataAny,
        external_id_field: str,
        batch_size: int = 10000,
        use_serial: bool = False,
        wait: int = 5,
        bypass_results: bool = False,
    ) -> AsyncIterator[Any]:
        """upsert records based on a unique identifier

        Data is batched by 10,000 records by default. To pick a lower size
        pass smaller integer to `batch_size`. to let simple-salesforce pick
        the appropriate limit dynamically, enter `batch_size='auto'`
        """
        return self._bulk_operation(
            use_serial=use_serial,
            operation="upsert",
            external_id_field=external_id_field,
            data=data,
            batch_size=batch_size,
            wait=wait,
            bypass_results=bypass_results,
        )

    async def update(
        self,
        data: BulkDataAny,
        batch_size: int = 10000,
        use_serial: bool = False,
        wait: int = 5,
        bypass_results: bool = False,
    ) -> AsyncIterator[Any]:
        """update records

        Data is batched by 10,000 records by default. To pick a lower size
        pass smaller integer to `batch_size`. to let simple-salesforce pick
        the appropriate limit dynamically, enter `batch_size='auto'`
        """
        return self._bulk_operation(
            use_serial=use_serial,
            operation="update",
            data=data,
            batch_size=batch_size,
            wait=wait,
            bypass_results=bypass_results,
        )

    async def hard_delete(
        self, data: BulkDataStr, batch_size: int = 10000, use_serial: bool = False, wait: int = 5, bypass_results: bool = False
    ) -> AsyncIterator[Any]:
        """hard delete records

        Data is batched by 10,000 records by default. To pick a lower size
        pass smaller integer to `batch_size`. to let simple-salesforce pick
        the appropriate limit dynamically, enter `batch_size='auto'`
        """
        return self._bulk_operation(
            use_serial=use_serial,
            operation="hardDelete",
            data=data,
            batch_size=batch_size,
            wait=wait,
            bypass_results=bypass_results,
        )

    async def query(self, data: BulkDataStr, lazy_operation: bool = False, wait: int = 5) -> AsyncIterator[Any]:
        """bulk query"""
        results = self._bulk_operation(operation="query", data=data, wait=wait)

        if lazy_operation:
            return results

        return await alist_from_generator(results)

    async def query_all(self, data: BulkDataStr, lazy_operation: bool = False, wait: int = 5) -> AsyncIterator[Any]:
        """bulk queryAll"""
        results = self._bulk_operation(operation="queryAll", data=data, wait=wait)

        if lazy_operation:
            return results
        return await alist_from_generator(results)
