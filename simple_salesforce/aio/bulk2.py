""" Classes for interacting with Salesforce Bulk 2.0 API """
import asyncio
import copy
import csv
import http.client as http
import io
import json
import os
import re
import sys
import tempfile
from collections import OrderedDict
from contextlib import aclosing
from typing import Dict, Tuple, Union, List

import aiofiles
import math
import pendulum
from pendulum import DateTime

from simple_salesforce.exceptions import (
    SalesforceBulkV2ExtractError,
    SalesforceBulkV2LoadError,
    SalesforceOperationError,
)
from simple_salesforce.bulk2 import (
    Operation,
    JobState,
    ColumnDelimiter,
    LineEnding,
    ResultsType,
    _delimiter_char,  # Dedupe from upstream
    _line_ending_char,  # Dedupe from upstream
    MAX_INGEST_JOB_FILE_SIZE,
    DEFAULT_QUERY_PAGE_SIZE,
)
from .aio_util import call_salesforce, create_session_factory


# pylint: disable=missing-class-docstring,invalid-name,too-many-arguments,
# too-many-locals


async def _split_csv(filename=None, records=None, max_records: int = None):
    """Split a CSV file into chunks to avoid exceeding the Salesforce
    bulk 2.0 API limits.

    Arguments:
        * filename -- csv file
        * max_records -- the number of records per chunk, None for auto size
    """
    if filename:
        total_records = await _count_csv(filename=filename, skip_header=True)
    else:
        total_records = await _count_csv(data=records, skip_header=True)

    csv_data_size = os.path.getsize(filename) if filename else sys.getsizeof(records)
    max_records = max_records or total_records
    max_records = min(max_records, total_records)
    max_bytes = min(
        csv_data_size, MAX_INGEST_JOB_FILE_SIZE - 1 * 1024 * 1024
    )  # -1 MB for sentinel
    records_size = 0
    bytes_size = 0
    buff = []
    if filename:
        async with aiofiles.open(filename, encoding="utf-8") as bis:
            header = None
            async for line in bis:
                if header is None:
                    header = line
                    continue

                records_size += 1
                bytes_size += len(line.encode("utf-8"))
                if records_size > max_records or bytes_size > max_bytes:
                    if buff:
                        yield records_size - 1, header + "".join(buff)
                    buff = [line]
                    records_size = 1
                    bytes_size = len(line.encode("utf-8"))
                else:
                    buff.append(line)
            if buff:
                yield records_size, header + "".join(buff)
    else:
        header = records.splitlines(True)[0]
        for line in records.splitlines(True)[1:]:
            records_size += 1
            bytes_size += len(line.encode("utf-8"))
            if records_size > max_records or bytes_size > max_bytes:
                if buff:
                    yield records_size - 1, header + "".join(buff)
                buff = [line]
                records_size = 1
                bytes_size = len(line.encode("utf-8"))
            else:
                buff.append(line)
        if buff:
            yield records_size, header + "".join(buff)


async def _count_csv(filename=None, data=None, skip_header=False, line_ending=LineEnding.LF):
    """Count the number of records in a CSV file."""
    if filename:
        count = 0
        async with aiofiles.open(filename, encoding="utf-8") as bis:
            async for _ in bis:
                count += 1
    elif data:
        pat = repr(_line_ending_char[line_ending])[1:-1]
        count = sum(1 for _ in re.finditer(pat, data))
    else:
        raise ValueError("Either filename or data must be provided")

    if skip_header:
        count -= 1
    return count


def _convert_dict_to_csv(data, column_delimiter=",", line_ending=LineEnding.LF) -> str:
    """Converts list of dicts to CSV like object."""
    if data:
        keys = set(i for s in [d.keys() for d in data] for i in s)
        dict_to_csv_file = io.StringIO()
        writer = csv.DictWriter(
            dict_to_csv_file,
            fieldnames=keys,
            delimiter=column_delimiter,
            lineterminator=line_ending,
        )
        writer.writeheader()
        for row in data:
            writer.writerow(row)
    return dict_to_csv_file.getvalue() if data else None


class AsyncSFBulk2Handler:
    """Bulk 2.0 API request handler
    Intermediate class which allows us to use commands,
     such as 'sf.bulk2.Contacts.insert(...)'
    This is really just a middle layer, whose sole purpose is
    to allow the above syntax
    """

    def __init__(self, session_id, bulk2_url,  proxies, session_factory):
        """Initialize the instance with the given parameters.

        Arguments:

        * session_id -- the session ID for authenticating to Salesforce
        * bulk2_url -- 2.0 API endpoint set in Salesforce instance
        * proxies -- the optional map of scheme to proxy server
        * session_factory -- Function to return a custom httpx session (AsyncClient).
                             This enables the use of httpx Session features not otherwise
                             exposed by simple_salesforce.
        """
        self.session_id = session_id
        self.session_factory = session_factory
        self.bulk2_url = bulk2_url
        # don't wipe out original proxies with None
        if not self.session_factory:
            self.session_factory = create_session_factory(proxies=proxies)

        # Define these headers separate from Salesforce class,
        # as bulk uses a slightly different format
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + self.session_id,
            "X-PrettyPrint": "1",
        }

    def __getattr__(self, name):
        return AsyncSFBulk2Type(
            object_name=name,
            bulk2_url=self.bulk2_url,
            headers=self.headers,
            session_factory=self.session_factory,
        )


class _AsyncBulk2Client:
    """Bulk 2.0 API client"""

    JSON_CONTENT_TYPE = "application/json"
    CSV_CONTENT_TYPE = "text/csv"

    DEFAULT_WAIT_TIMEOUT_SECONDS = 86400  # 24-hour bulk job running time
    MAX_CHECK_INTERVAL_SECONDS = 2.0

    def __init__(self, object_name, bulk2_url, headers, session_factory):
        """
        Arguments:

        * object_name -- the name of the type of SObject this represents,
                         e.g. `Lead` or `Contact`
        * bulk2_url -- 2.0 API endpoint set in Salesforce instance
        * headers -- bulk 2.0 API headers
        * session_factory -- Function to return a custom httpx session (AsyncClient).
                             This enables the use of httpx Session features not otherwise
                             exposed by simple_salesforce.
        """
        self.object_name = object_name
        self.bulk2_url = bulk2_url
        self.session_factory = session_factory
        self.headers = headers

    def _get_headers(self, request_content_type=None, accept_content_type=None):
        """Get headers for bulk 2.0 API request"""
        headers = copy.deepcopy(self.headers)
        headers["Content-Type"] = request_content_type or self.JSON_CONTENT_TYPE
        headers["ACCEPT"] = accept_content_type or self.JSON_CONTENT_TYPE
        return headers

    def _construct_request_url(self, job_id, is_query: bool):
        """Construct bulk 2.0 API request URL"""
        if not job_id:
            job_id = ""
        if is_query:
            url = self.bulk2_url + "query"
        else:
            url = self.bulk2_url + "ingest"
        if job_id:
            url = f"{url}/{job_id}"
        return url

    async def create_job(
        self,
        operation,
        query=None,
        column_delimiter=ColumnDelimiter.COMMA,
        line_ending=LineEnding.LF,
        external_id_field=None,
    ):
        """Create job

        Arguments:

        * operation -- Bulk operation to be performed by job
        * query -- SOQL query to be performed by job
        * column_delimiter -- The column delimiter used for CSV job data
        * line_ending -- The line ending used for CSV job data
        * external_id_field -- The external ID field in the object being updated
        """
        payload = {
            "operation": operation,
            "columnDelimiter": column_delimiter,
            "lineEnding": line_ending,
        }
        if external_id_field:
            payload["externalIdFieldName"] = external_id_field

        is_query = operation in (Operation.query, Operation.query_all)
        url = self._construct_request_url(None, is_query)
        if is_query:
            headers = self._get_headers(self.JSON_CONTENT_TYPE, self.CSV_CONTENT_TYPE)
            if not query:
                raise SalesforceBulkV2ExtractError("Query is required for query jobs")
            payload["query"] = query
        else:
            headers = self._get_headers(self.JSON_CONTENT_TYPE, self.JSON_CONTENT_TYPE)
            payload["object"] = self.object_name
            payload["contentType"] = "CSV"
        result = await call_salesforce(
            url=url,
            method="POST",
            session_factory=self.session_factory,
            headers=headers,
            data=json.dumps(payload, allow_nan=False),
        )
        return result.json(object_pairs_hook=OrderedDict)

    async def wait_for_job(self, job_id, is_query: bool, wait=0.5):
        """Wait for job completion or timeout"""
        expiration_time: DateTime = pendulum.now().add(
            seconds=self.DEFAULT_WAIT_TIMEOUT_SECONDS
        )
        job_status = JobState.in_progress if is_query else JobState.open
        delay_timeout = 0.0
        delay_cnt = 0
        await asyncio.sleep(wait)
        while pendulum.now() < expiration_time:
            job_info = await self.get_job(job_id, is_query)
            job_status = job_info["state"]
            if job_status in [
                JobState.job_complete,
                JobState.aborted,
                JobState.failed,
            ]:
                if job_status != JobState.job_complete:
                    error_message = job_info.get("errorMessage") or job_info
                    raise SalesforceOperationError(
                        f"Job failure. Response content: {error_message}"
                    )
                return job_status  # JobComplete

            if delay_timeout < self.MAX_CHECK_INTERVAL_SECONDS:
                delay_timeout = wait + math.exp(delay_cnt) / 1000.0
                delay_cnt += 1
            await asyncio.sleep(delay_timeout)
        raise SalesforceOperationError(f"Job timeout. Job status: {job_status}")

    async def abort_job(self, job_id, is_query: bool):
        """Abort query/ingest job"""
        return await self._set_job_state(job_id, is_query, JobState.aborted)

    async def close_job(self, job_id):
        """Close ingest job"""
        return await self._set_job_state(job_id, False, JobState.upload_complete)

    async def delete_job(self, job_id, is_query: bool):
        """Delete query/ingest job"""
        url = self._construct_request_url(job_id, is_query)
        headers = self._get_headers()
        result = await call_salesforce(
            url=url, method="DELETE", session_factory=self.session_factory, headers=headers
        )
        return result.json(object_pairs_hook=OrderedDict)

    async def _set_job_state(self, job_id, is_query: bool, state: str):
        """Set job state"""
        url = self._construct_request_url(job_id, is_query)
        headers = self._get_headers()
        payload = {"state": state}
        result = await call_salesforce(
            url=url,
            method="PATCH",
            session_factory=self.session_factory,
            headers=headers,
            data=json.dumps(payload, allow_nan=False),
        )
        return result.json(object_pairs_hook=OrderedDict)

    async def get_job(self, job_id, is_query: bool):
        """Get job info"""
        url = self._construct_request_url(job_id, is_query)

        result = await call_salesforce(
            url=url, method="GET", session_factory=self.session_factory, headers=self._get_headers()
        )
        return result.json(object_pairs_hook=OrderedDict)

    def filter_null_bytes(self, b: Union[str, bytes]):
        """
        https://github.com/airbytehq/airbyte/issues/8300
        """
        if isinstance(b, str):
            return b.replace("\x00", "")
        if isinstance(b, bytes):
            return b.replace(b"\x00", b"")
        raise TypeError("Expected str or bytes")

    async def get_query_results(
        self, job_id, locator: str = "", max_records=DEFAULT_QUERY_PAGE_SIZE
    ):
        """Get results for a query job"""
        url = self._construct_request_url(job_id, True) + "/results"
        params = {"maxRecords": max_records}
        if locator and locator != "null":
            params["locator"] = locator
        headers = self._get_headers(self.JSON_CONTENT_TYPE, self.CSV_CONTENT_TYPE)
        result = await call_salesforce(
            url=url,
            method="GET",
            session_factory=self.session_factory,
            headers=headers,
            params=params,
        )
        locator = result.headers.get("Sforce-Locator", "")
        if locator == "null":
            locator = ""
        number_of_records = int(result.headers.get("Sforce-NumberOfRecords"))
        return {
            "locator": locator,
            "number_of_records": number_of_records,
            "records": self.filter_null_bytes(result.text),
        }

    async def download_job_data(
        self,
        path,
        job_id,
        locator: str = "",
        max_records=DEFAULT_QUERY_PAGE_SIZE,
        chunk_size=1024,
    ):
        """Get results for a query job"""
        if not os.path.exists(path):
            raise SalesforceBulkV2LoadError(f"Path does not exist: {path}")

        url = self._construct_request_url(job_id, True) + "/results"
        params = {"maxRecords": max_records}
        if locator and locator != "null":
            params["locator"] = locator
        headers = self._get_headers(self.JSON_CONTENT_TYPE, self.CSV_CONTENT_TYPE)
        # Close connection without contextlib
        async with aclosing(
            await call_salesforce(
                url=url,
                method="GET",
                session_factory=self.session_factory,
                headers=headers,
                params=params,
                stream=True,
            )
        ) as result, tempfile.NamedTemporaryFile(
            "wb", dir=path, suffix=".csv", delete=False
        ) as bos:
            locator = result.headers.get("Sforce-Locator", "")
            if locator == "null":
                locator = ""
            number_of_records = int(result.headers.get("Sforce-NumberOfRecords"))
            for chunk in result.iter_content(chunk_size=chunk_size):
                bos.write(self.filter_null_bytes(chunk))
            # check the file exists
            if os.path.isfile(bos.name):
                return {
                    "locator": locator,
                    "number_of_records": number_of_records,
                    "file": bos.name,
                }
            raise SalesforceBulkV2LoadError(
                f"The IO/Error occured while verifying binary data. "
                f"File {bos.name} doesn't exist, url: {url}, "
            )

    async def upload_job_data(self, job_id, data: str, content_url=None):
        """Upload job data"""
        if not data:
            raise SalesforceBulkV2LoadError("Data is required for ingest jobs")

        # performance reduction here
        data_size = len(data.encode("utf-8"))
        if data_size > MAX_INGEST_JOB_FILE_SIZE:
            raise SalesforceBulkV2LoadError(
                f"Data size {data_size} exceeds the max file size accepted by "
                "Bulk V2 (100 MB)"
            )

        url = content_url or self._construct_request_url(job_id, False) + "/batches"
        headers = self._get_headers(self.CSV_CONTENT_TYPE, self.JSON_CONTENT_TYPE)
        result = await call_salesforce(
            url=url,
            method="PUT",
            session_factory=self.session_factory,
            headers=headers,
            data=data,
        )
        if result.status_code != http.CREATED:
            raise SalesforceBulkV2LoadError(
                f"Failed to upload job data. Error Code {result.status_code}. "
                f"Response content: {result.content}"
            )

    async def get_ingest_results(self, job_id, results_type):
        """Get record results"""
        url = self._construct_request_url(job_id, False) + "/" + results_type
        headers = self._get_headers(self.JSON_CONTENT_TYPE, self.CSV_CONTENT_TYPE)
        result = await call_salesforce(
            url=url, method="GET", session_factory=self.session_factory, headers=headers
        )
        return result.text

    async def download_ingest_results(self, file, job_id, results_type, chunk_size=1024):
        """Download record results to a file"""
        url = self._construct_request_url(job_id, False) + "/" + results_type
        headers = self._get_headers(self.JSON_CONTENT_TYPE, self.CSV_CONTENT_TYPE)
        async with aclosing(
            await call_salesforce(
                url=url, method="GET", session_factory=self.session_factory, headers=headers
            )
        ) as result, open(file, "wb") as bos:
            for chunk in result.iter_content(chunk_size=chunk_size):
                bos.write(self.filter_null_bytes(chunk))

        if not os.path.exists(file):
            raise SalesforceBulkV2LoadError(
                f"The IO/Error occured while verifying binary data. "
                f"File {file} doesn't exist, url: {url}, "
            )


class AsyncSFBulk2Type:
    """Interface to Bulk 2.0 API functions"""

    def __init__(self, object_name, bulk2_url, headers, session_factory):
        """Initialize the instance with the given parameters.

        Arguments:

        * object_name -- the name of the type of SObject this represents,
                         e.g. `Lead` or `Contact`
        * bulk2_url -- API endpoint set in Salesforce instance
        * headers -- bulk API headers
        * session_factory -- Function to return a custom httpx session (AsyncClient).
                             This enables the use of httpx Session features not otherwise
                             exposed by simple_salesforce.
        """
        self.object_name = object_name
        self.bulk2_url = bulk2_url
        self.session_factory = session_factory
        self.headers = headers
        self._client = _AsyncBulk2Client(object_name, bulk2_url, headers, session_factory)

    async def _upload_data(
        self,
        operation,
        data: Union[str, Tuple[int, str]],
        column_delimiter=ColumnDelimiter.COMMA,
        line_ending=LineEnding.LF,
        external_id_field=None,
        wait=5,
    ) -> Dict:
        """Upload data to Salesforce"""
        if len(data) == 2:
            total, data = data
        else:
            total = await _count_csv(data=data, line_ending=line_ending, skip_header=True)
        res = await self._client.create_job(
            operation,
            column_delimiter=column_delimiter,
            line_ending=line_ending,
            external_id_field=external_id_field,
        )
        job_id = res["id"]
        try:
            if res["state"] == JobState.open:
                await self._client.upload_job_data(job_id, data)
                await self._client.close_job(job_id)
                await self._client.wait_for_job(job_id, False, wait)
                res = await self._client.get_job(job_id, False)
                return {
                    "numberRecordsFailed": int(res["numberRecordsFailed"]),
                    "numberRecordsProcessed": int(res["numberRecordsProcessed"]),
                    "numberRecordsTotal": int(total),
                    "job_id": job_id,
                }
            raise SalesforceBulkV2LoadError(
                f"Failed to upload job data. Response content: {res}"
            )
        except Exception:
            res = await self._client.get_job(job_id, False)
            if res["state"] in (
                JobState.upload_complete,
                JobState.in_progress,
                JobState.open,
            ):
                await self._client.abort_job(job_id, False)
            raise

    # pylint:disable=too-many-locals
    async def _upload_file(
        self,
        operation,
        csv_file=None,
        records=None,
        batch_size=None,
        column_delimiter=ColumnDelimiter.COMMA,
        line_ending=LineEnding.LF,
        external_id_field=None,
        wait=5,
    ) -> List[Dict]:
        """Upload csv file to Salesforce"""
        if csv_file and records:
            raise SalesforceBulkV2LoadError("Cannot include both file and " "records")
        if not records and csv_file:
            if not os.path.exists(csv_file):
                raise SalesforceBulkV2LoadError(csv_file + " not found.")

        if operation in (Operation.delete, Operation.hard_delete):
            async with aiofiles.open(csv_file, "r", encoding="utf-8") as bis:
                header = await anext(bis, None)
                if header is None:
                    raise SalesforceBulkV2LoadError(
                        f"InvalidBatch: The '{operation}' batch must contain "
                        f"only ids, {header}"
                    )
                else:
                    header = header.rstrip().split(_delimiter_char[column_delimiter])

                    if len(header) != 1:
                        raise SalesforceBulkV2LoadError(
                            f"InvalidBatch: The '{operation}' batch must contain "
                            f"only ids, {header}"
                        )

        results = []
        if csv_file:
            split_data = _split_csv(filename=csv_file, max_records=batch_size)
        else:
            split_data = _split_csv(records=records, max_records=batch_size)

        futures = []
        async for data in split_data:
            futures.append(self._upload_data(
                operation,
                data,
                column_delimiter,
                line_ending,
                external_id_field,
                wait,
            ))
        results = await asyncio.gather(*futures)
        return results

    async def delete(
        self,
        csv_file=None,
        records=None,
        batch_size=None,
        column_delimiter=ColumnDelimiter.COMMA,
        line_ending=LineEnding.LF,
        external_id_field=None,
        wait=5,
    ) -> List[Dict]:
        """soft delete records"""
        return await self._upload_file(
            Operation.delete,
            csv_file=csv_file,
            records=_convert_dict_to_csv(
                records,
                column_delimiter=_delimiter_char.get(column_delimiter),
                line_ending=_line_ending_char.get(line_ending),
            ),
            batch_size=batch_size,
            column_delimiter=column_delimiter,
            line_ending=line_ending,
            external_id_field=external_id_field,
            wait=wait,
        )

    async def insert(
        self,
        csv_file=None,
        records=None,
        batch_size=None,
        column_delimiter=ColumnDelimiter.COMMA,
        line_ending=LineEnding.LF,
        wait=5,
    ) -> List[Dict]:
        """insert records"""
        return await self._upload_file(
            Operation.insert,
            csv_file=csv_file,
            records=_convert_dict_to_csv(
                records,
                column_delimiter=_delimiter_char.get(column_delimiter),
                line_ending=_line_ending_char.get(line_ending),
            ),
            batch_size=batch_size,
            column_delimiter=column_delimiter,
            line_ending=line_ending,
            wait=wait,
        )

    async def upsert(
        self,
        csv_file=None,
        records=None,
        external_id_field="Id",
        batch_size=None,
        column_delimiter=ColumnDelimiter.COMMA,
        line_ending=LineEnding.LF,
        wait=5,
    ) -> List[Dict]:
        """upsert records based on a unique identifier"""
        return await self._upload_file(
            Operation.upsert,
            csv_file=csv_file,
            records=_convert_dict_to_csv(
                records,
                column_delimiter=_delimiter_char.get(column_delimiter),
                line_ending=_line_ending_char.get(line_ending),
            ),
            batch_size=batch_size,
            column_delimiter=column_delimiter,
            line_ending=line_ending,
            external_id_field=external_id_field,
            wait=wait,
        )

    async def update(
        self,
        csv_file=None,
        records=None,
        batch_size=None,
        column_delimiter=ColumnDelimiter.COMMA,
        line_ending=LineEnding.LF,
        wait=5,
    ) -> List[Dict]:
        """update records"""
        return await self._upload_file(
            Operation.update,
            csv_file=csv_file,
            records=_convert_dict_to_csv(
                records,
                column_delimiter=_delimiter_char.get(column_delimiter),
                line_ending=_line_ending_char.get(line_ending),
            ),
            batch_size=batch_size,
            column_delimiter=column_delimiter,
            line_ending=line_ending,
            wait=wait,
        )

    async def hard_delete(
        self,
        csv_file=None,
        records=None,
        batch_size=None,
        column_delimiter=ColumnDelimiter.COMMA,
        line_ending=LineEnding.LF,
        wait=5,
    ) -> List[Dict]:
        """hard delete records"""
        return await self._upload_file(
            Operation.hard_delete,
            csv_file=csv_file,
            records=_convert_dict_to_csv(
                records,
                column_delimiter=_delimiter_char.get(column_delimiter),
                line_ending=_line_ending_char.get(line_ending),
            ),
            batch_size=batch_size,
            column_delimiter=column_delimiter,
            line_ending=line_ending,
            wait=wait,
        )

    async def query(
        self,
        query,
        max_records=DEFAULT_QUERY_PAGE_SIZE,
        column_delimiter=ColumnDelimiter.COMMA,
        line_ending=LineEnding.LF,
        wait=5,
    ):
        """bulk 2.0 query

        Arguments:
        * query -- SOQL query
        * max_records -- max records to retrieve per batch, default 50000

        Returns:
        * locator  -- the locator for the next set of results
        * number_of_records -- the number of records in this set
        * records -- records in this set
        """
        res = await self._client.create_job(
            Operation.query, query, column_delimiter, line_ending
        )
        job_id = res["id"]
        await self._client.wait_for_job(job_id, True, wait)

        locator = "INIT"
        while locator:
            if locator == "INIT":
                locator = ""
            result = await self._client.get_query_results(job_id, locator, max_records)
            locator = result["locator"]
            yield result["records"]

    async def download(
        self,
        query,
        path,
        max_records=DEFAULT_QUERY_PAGE_SIZE,
        column_delimiter=ColumnDelimiter.COMMA,
        line_ending=LineEnding.LF,
        wait=5,
    ) -> List[Dict]:
        """bulk 2.0 query stream to file, avoiding high memory usage

        Arguments:
        * query -- SOQL query
        * max_records -- max records to retrieve per batch, default 50000

        Returns:
        * locator  -- the locator for the next set of results
        * number_of_records -- the number of records in this set
        * file -- downloaded file
        """
        if not os.path.exists(path):
            raise SalesforceBulkV2LoadError(f"Path does not exist: {path}")

        res = await self._client.create_job(
            Operation.query, query, column_delimiter, line_ending
        )
        job_id = res["id"]
        await self._client.wait_for_job(job_id, True, wait)

        results = []
        locator = "INIT"
        while locator:
            if locator == "INIT":
                locator = ""
            result = await self._client.download_job_data(path, job_id, locator, max_records)
            locator = result["locator"]
            results.append(result)
        return results

    async def _retrieve_ingest_records(self, job_id, results_type, file=None):
        """Retrieve the results of an ingest job"""
        if not file:
            return self._client.get_ingest_results(job_id, results_type)
        await self._client.download_ingest_results(file, job_id, results_type)
        return ""

    async def get_failed_records(self, job_id, file=None):
        """Get failed record results

        Results Property:
            sf__Id:	[string] ID of the record
            sf__Error:	[Error]	Error code and message
            Fields from the original CSV request data:	various
        """
        return await self._retrieve_ingest_records(job_id, ResultsType.failed, file)

    async def get_unprocessed_records(self, job_id, file=None):
        """Get unprocessed record results

        Results Property:
            Fields from the original CSV request data:	[various]
        """
        return await self._retrieve_ingest_records(job_id, ResultsType.unprocessed, file)

    async def get_successful_records(self, job_id, file=None):
        """Get successful record results.

        Results Property:
            sf__Id:	[string] ID of the record
            sf__Created: [boolean] Indicates if the record was created
            Fields from the original CSV request data:	[various]
        """
        return await self._retrieve_ingest_records(job_id, ResultsType.successful, file)

    async def get_all_ingest_records(self, job_id, file=None):
        """Get all ingest record results for job

        Results Property:
            sf__Id:	[string] ID of the record
            sf__Created: [boolean] Indicates if the record was created
            Fields from the original CSV request data:	[various]
            Fields: [various] Fields from the original CSV request data
        """
        successful, failed, unprocessed = await asyncio.gather(
            self.get_successful_records(job_id=job_id, file=file).splitlines(),
            self.get_failed_records(job_id=job_id, file=file).splitlines(),
            self.get_unprocessed_records(job_id=job_id, file=file).splitlines()
        )
        successful_records = csv.DictReader(
            successful,
            delimiter=",",
            lineterminator="\n",
        )
        failed_records = csv.DictReader(
            failed,
            delimiter=",",
            lineterminator="\n",
        )
        unprocessed_records = csv.DictReader(
            unprocessed,
            delimiter=",",
            lineterminator="\n",
        )
        return {
            "successfulRecords": list(successful_records),
            "failedRecords": list(failed_records),
            "unprocessedRecords": list(unprocessed_records),
        }
