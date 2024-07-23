"""Test for bulk2.py"""
import csv
import http.client as http
import json
import os
import re
import tempfile
import textwrap
from contextlib import contextmanager
from functools import partial

import aiofiles
import pytest
from pytest_httpx import HTTPXMock

from simple_salesforce.bulk2 import JobState, Operation

# pylint: disable=line-too-long,missing-docstring

to_body = partial(json.dumps, ensure_ascii=False)



@pytest.fixture
def assert_all_responses_were_requested() -> bool:
    # Disable checking httpx_mock for unrequested responses
    return False


@contextmanager
def to_csv_file(data):
    """Create a temporary csv file from a list of dicts, delete it when done."""
    temp_file = None
    try:
        temp_file = tempfile.NamedTemporaryFile(mode="w", delete=False)
        writer = csv.DictWriter(temp_file, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)
        temp_file.flush()
        yield temp_file.name
    finally:
        if temp_file is not None:
            os.remove(temp_file.name)


@contextmanager
def temp_csv_file():
    temp_file = None
    try:
        temp_file = tempfile.NamedTemporaryFile(delete=False)
        yield temp_file.name
    finally:
        if temp_file is not None:
            os.remove(temp_file.name)


def test_bulk2_handler(sf_client, constants):
    """Test bulk2 handler creation"""

    bulk2_handler = sf_client.bulk2
    assert bulk2_handler.session_id == sf_client.session_id
    assert bulk2_handler.bulk2_url == sf_client.bulk2_url
    assert constants["BULK2_HEADERS"] == bulk2_handler.headers


def test_bulk2_type(sf_client, constants):
    """Test bulk2 type creation"""

    contact = sf_client.bulk2.Contact
    assert contact.bulk2_url == sf_client.bulk2_url
    assert constants["BULK2_HEADERS"] == contact.headers
    assert "Contact" == contact.object_name



@pytest.fixture
def ingest_responses(httpx_mock: HTTPXMock):
    def build_response(operation, processed, failed=0):
        """Mock responses for bulk2 ingest jobs"""
        httpx_mock.add_response(
            status_code=http.OK,
            url=re.compile(r"^https://.*/jobs/ingest$"),
            method="POST",
            json={
                "apiVersion": 52.0,
                "columnDelimiter": "COMMA",
                "concurrencyMode": "Parallel",
                "contentType": "CSV",
                "id": "Job-1",
                "jobType": "V2Ingest",
                "lineEnding": "LF",
                "object": "Contact",
                "operation": operation,
                "state": JobState.open,
            }
        )
        httpx_mock.add_response(
            status_code=http.CREATED,
            url=re.compile(r"^https://.*/jobs/ingest/Job-1/batches$"),
            method="PUT",
        )
        httpx_mock.add_response(
            status_code=http.OK,
            url=re.compile(r"^https://.*/jobs/ingest/Job-1$"),
            method="PATCH",
            json={
                "apiVersion": 52.0,
                "columnDelimiter": "COMMA",
                "concurrencyMode": "Parallel",
                "contentType": "CSV",
                "id": "Job-1",
                "jobType": "V2Ingest",
                "lineEnding": "LF",
                "object": "Contact",
                "operation": operation,
                "state": JobState.upload_complete,
            }
        )
        httpx_mock.add_response(
            status_code=http.OK,
            url=re.compile(r"^https://.*/jobs/ingest/Job-1$"),
            method="GET",
            json={
                "apiVersion": 52.0,
                "columnDelimiter": "COMMA",
                "concurrencyMode": "Parallel",
                "contentType": "CSV",
                "id": "Job-1",
                "jobType": "V2Ingest",
                "lineEnding": "LF",
                "object": "Contact",
                "operation": operation,
                "state": JobState.in_progress,
            }
        )
        httpx_mock.add_response(
            status_code=http.OK,
            url=re.compile(r"^https://.*/jobs/ingest/Job-1$"),
            method="GET",
            json={
                "apiVersion": 52.0,
                "columnDelimiter": "COMMA",
                "concurrencyMode": "Parallel",
                "contentType": "CSV",
                "id": "Job-1",
                "jobType": "V2Ingest",
                "lineEnding": "LF",
                "numberRecordsFailed": failed,
                "numberRecordsProcessed": processed,
                "object": "Contact",
                "operation": operation,
                "state": JobState.job_complete,
            }
        )
    return build_response


async def ingest_data(sf_client, operation, data, **kwargs):
    """Upload data into Salesforce"""
    operation = (
        "hard_delete" if operation == Operation.hard_delete else operation
    )
    with to_csv_file(data) as csv_file:
        handler = getattr(sf_client.bulk2.Contact, operation)
        results = await handler(csv_file, **kwargs)
    return results


EXPECTED_RESULTS = [
    {
        "numberRecordsFailed": 0,
        "numberRecordsProcessed": 2,
        "numberRecordsTotal": 2,
        "job_id": "Job-1",
    }
]
EXPECTED_QUERY = [
    textwrap.dedent(
        """
        "Id","AccountId","Email","FirstName","LastName"
        "001xx000003DHP0AAO","ID-13","contact1@example.com","Bob","x"
        "001xx000003DHP1AAO","ID-24","contact2@example.com","Alice","y"
        "001xx000003DHP0AAO","ID-13","contact1@example.com","Bob","x"
        "001xx000003DHP1AAO","ID-24","contact2@example.com","Alice","y"
        """
    )
]
INSERT_DATA = [
    {
        "Custom_Id__c": "CustomID1",
        "AccountId": "ID-13",
        "Email": "contact1@example.com",
        "FirstName": "Bob",
        "LastName": "x",
    },
    {
        "Custom_Id__c": "CustomID2",
        "AccountId": "ID-24",
        "Email": "contact2@example.com",
        "FirstName": "Alice",
        "LastName": "y",
    },
]
UPSERT_DATA = [
    {
        "Custom_Id__c": "CustomID1",
        "LastName": "X",
    },
    {
        "Custom_Id__c": "CustomID2",
        "LastName": "Y",
    },
]
DELETE_DATA = [
    {"Id": "a011s00000DTU9zAAH"},
    {"Id": "a011s00000DTUA0AAP"},
]


async def test_sf_bulk2_type_insert(httpx_mock, sf_client, ingest_responses):
    """Test bulk2 insert records"""
    operation = Operation.insert
    total = len(INSERT_DATA)
    ingest_responses(operation, processed=total, failed=0)
    results = await ingest_data(sf_client, operation, INSERT_DATA)
    assert EXPECTED_RESULTS == results

    httpx_mock.add_response(
        url=re.compile(r"^https://.*/jobs/ingest/Job-1/successfulResults$"),
        method="GET",
        text=textwrap.dedent(
            """
            "sf__Id","sf__Created","Custom_Id__c","AccountId","Email","FirstName","LastName"
            "a011s00000DML8XAAX","true","CustomID1","ID-13","contact1@example.com","Bob","x"
            "a011s00000DML8YAAX","true","CustomID2","ID-24","contact2@example.com","Alice","y"
            """
        )
    )

    results = await sf_client.bulk2.Contact.get_successful_records("Job-1")

    assert textwrap.dedent("""
        "sf__Id","sf__Created","Custom_Id__c","AccountId","Email","FirstName","LastName"
        "a011s00000DML8XAAX","true","CustomID1","ID-13","contact1@example.com","Bob","x"
        "a011s00000DML8YAAX","true","CustomID2","ID-24","contact2@example.com","Alice","y"
        """
    ) == results


async def test_sf_bulk2_type_upsert(httpx_mock, sf_client, ingest_responses):
    """Test bulk2 upsert records"""
    operation = Operation.upsert
    total = len(UPSERT_DATA)
    ingest_responses(operation, processed=total, failed=0)
    results = await ingest_data(
        sf_client, operation, UPSERT_DATA, external_id_field="Custom_Id__c"
    )
    assert EXPECTED_RESULTS == results
    httpx_mock.add_response(
        url=re.compile(r"^https://.*/jobs/ingest/Job-1/successfulResults$"),
        method="GET",
        text=textwrap.dedent(
            """
            "sf__Id","sf__Created","Custom_Id__c","LastName"
            "a011s00000DML8XAAX","false","CustomID1","X"
            "a011s00000DML8YAAX","false","CustomID2","Y"
            """
        )
    )

    results = sf_client.bulk2.Contact.get_successful_records("Job-1")
    assert textwrap.dedent(
            """
                "sf__Id","sf__Created","Custom_Id__c","LastName"
                "a011s00000DML8XAAX","false","CustomID1","X"
                "a011s00000DML8YAAX","false","CustomID2","Y"
            """
        ) == results


async def test_hard_delete(httpx_mock, sf_client, ingest_responses):
    """Test bulk2 hardDelete records"""
    operation = Operation.hard_delete
    total = len(DELETE_DATA)
    ingest_responses(operation, processed=total, failed=0)
    results = await ingest_data(sf_client, operation, DELETE_DATA)
    assert EXPECTED_RESULTS == results

    httpx_mock.add_response(
        method="GET",
        url=re.compile(r"^https://.*/jobs/ingest/Job-1/successfulResults$"),
        text=textwrap.dedent(
            """
            "sf__Id","sf__Created","Id"
            "a011s00000DTU9zAAH","false","a011s00000DTU9zAAH"
            "a011s00000DTUA0AAP","false","a011s00000DTUA0AAP"
            """
        ),
        status_code=http.OK,
    )

    results = await sf_client.bulk2.Contact.get_successful_records("Job-1")
    assert textwrap.dedent(
            """
            "sf__Id","sf__Created","Id"
            "a011s00000DTU9zAAH","false","a011s00000DTU9zAAH"
            "a011s00000DTUA0AAP","false","a011s00000DTUA0AAP"
            """
        ) == results


async def test_query(httpx_mock, sf_client):
    """Test bulk2 query records"""
    operation = Operation.query
    httpx_mock.add_response(
        method="POST",
        url=re.compile(r"^https://.*/jobs/query$"),
        text=to_body(
            {
                "apiVersion": 52.0,
                "columnDelimiter": "COMMA",
                "concurrencyMode": "Parallel",
                "contentType": "CSV",
                "id": "Job-1",
                "lineEnding": "LF",
                "object": "Contact",
                "operation": operation,
                "state": JobState.upload_complete,
            }
        ),
        status_code=http.OK,
    )
    httpx_mock.add_response(
        method="GET",
        url=re.compile(r"^https://.*/jobs/query/Job-1$"),
        text=to_body(
            {
                "apiVersion": 52.0,
                "columnDelimiter": "COMMA",
                "concurrencyMode": "Parallel",
                "contentType": "CSV",
                "id": "Job-1",
                "jobType": "V2Query",
                "lineEnding": "LF",
                "numberRecordsProcessed": 4,
                "object": "Contact",
                "operation": operation,
                "state": JobState.in_progress,
            }
        ),
        status_code=http.OK,
    )
    httpx_mock.add_response(
        method="GET",
        url=re.compile(r"^https://.*/jobs/query/Job-1$"),
        text=to_body(
            {
                "apiVersion": 52.0,
                "columnDelimiter": "COMMA",
                "concurrencyMode": "Parallel",
                "contentType": "CSV",
                "id": "Job-1",
                "jobType": "V2Query",
                "lineEnding": "LF",
                "numberRecordsProcessed": 4,
                "object": "Contact",
                "operation": operation,
                "state": JobState.job_complete,
            }
        ),
        status_code=http.OK,
    )
    httpx_mock.add_response(
        method="GET",
        url=re.compile(
            r"^https://.*/jobs/query/Job-1/results\?maxRecords=\d+$"
        ),
        text=textwrap.dedent(
            """
            "Id","AccountId","Email","FirstName","LastName"
            "001xx000003DHP0AAO","ID-13","contact1@example.com","Bob","x"
            "001xx000003DHP1AAO","ID-24","contact2@example.com","Alice","y"
            "001xx000003DHP0AAO","ID-13","contact1@example.com","Bob","x"
            "001xx000003DHP1AAO","ID-24","contact2@example.com","Alice","y"
            """
        ),
        headers={
            "Sforce-NumberOfRecords": "4",
            "Sforce-Query-Locator": "",
        },
        status_code=http.OK,
    )

    query = "SELECT Id,AccountId,Email,FirstName,LastName FROM Contact"
    results = []
    async for result in sf_client.bulk2.Contact.query(query):
        results.append(result)
    assert EXPECTED_QUERY == results


async def test_get_failed_record_results(httpx_mock, sf_client, ingest_responses):
    """Test bulk2 get failed records"""
    operation = Operation.insert
    total = len(INSERT_DATA)
    ingest_responses(
        operation,
        processed=total,
        failed=total,
    )
    results = await ingest_data(sf_client, operation, INSERT_DATA)
    assert [
            {
                "numberRecordsFailed": total,
                "numberRecordsProcessed": total,
                "numberRecordsTotal": total,
                "job_id": "Job-1",
            }
        ] == results


    def make_responses():
        httpx_mock.add_response(
            method="GET",
            url=re.compile(r"^https://.*/jobs/ingest/Job-1/failedResults$"),
            text=textwrap.dedent(
                """
                    "sf__Id","sf__Error","Custom_Id__c","AccountId","Email","FirstName","LastName"
                    "","UNABLE_TO_LOCK_ROW","CustomID1","ID-13","contact1@example.com","Bob","x"
                    "","UNABLE_TO_LOCK_ROW","CustomID2","ID-24","contact2@example.com","Alice","y"
                    """
            ),
            status_code=http.OK,
        )

    expected_results = textwrap.dedent(
        """
            "sf__Id","sf__Error","Custom_Id__c","AccountId","Email","FirstName","LastName"
            "","UNABLE_TO_LOCK_ROW","CustomID1","ID-13","contact1@example.com","Bob","x"
            "","UNABLE_TO_LOCK_ROW","CustomID2","ID-24","contact2@example.com","Alice","y"
            """
    )

    make_responses()
    failed_results = await sf_client.bulk2.Contact.get_failed_records("Job-1")
    assert expected_results == failed_results

    make_responses()
    with temp_csv_file() as csv_file:
        await sf_client.bulk2.Contact.get_failed_records("Job-1", file=csv_file)
        async with aiofiles.open(csv_file, "r", encoding="utf-8") as bis:
            content = await bis.read()
            assert expected_results == content


async def test_get_unprocessed_record_results(httpx_mock, sf_client, ingest_responses):
    """Test bulk2 get unprocessed records"""
    operation = Operation.insert
    total = len(INSERT_DATA)
    ingest_responses(
        operation,
        processed=total - 1,
        failed=0,
    )
    results = await ingest_data(sf_client, operation, INSERT_DATA)
    assert [
            {
                "numberRecordsFailed": 0,
                "numberRecordsProcessed": total - 1,
                "numberRecordsTotal": total,
                "job_id": "Job-1",
            }
        ] == results

    def make_responses():
        httpx_mock.add_response(
            method="GET",
            url=re.compile(
                r"^https://.*/jobs/ingest/Job-1/unprocessedRecords$"
            ),
            text=textwrap.dedent(
                """
                    "Custom_Id__c","AccountId","Email","FirstName","LastName"
                    "CustomID2","ID-24","contact2@example.com","Alice","y"
                    """
            ),
            status_code=http.OK,
        )

    expected_results = textwrap.dedent(
        """
        "Custom_Id__c","AccountId","Email","FirstName","LastName"
        "CustomID2","ID-24","contact2@example.com","Alice","y"
        """
    )

    make_responses()
    results = await sf_client.bulk2.Contact.get_unprocessed_records("Job-1")
    assert expected_results == results

    make_responses()
    with temp_csv_file() as csv_file:
        await sf_client.bulk2.Contact.get_unprocessed_records("Job-1", file=csv_file)
        async with aiofiles.open(csv_file, "r", encoding="utf-8") as bis:
            content = await bis.read()
            assert expected_results == content
