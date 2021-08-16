"""Test for bulk.py"""
import copy
import json
from unittest import mock

import httpx
import pytest


def test_bulk_handler(sf_client, constants):
    """Test that BulkHandler Loads Properly"""
    bulk_handler = sf_client.bulk
    assert bulk_handler.session_id == sf_client.session_id
    assert bulk_handler.bulk_url == sf_client.bulk_url
    assert constants["BULK_HEADERS"] == bulk_handler.headers


def test_bulk_type(sf_client, constants):
    """Test bulk type creation"""
    contact = sf_client.bulk.Contact
    assert contact.bulk_url == sf_client.bulk_url
    assert constants["BULK_HEADERS"] == contact.headers
    assert 'Contact' == contact.object_name


EXPECTED_RESULT = [
    {
        "success": True,
        "created": True,
        "id": "001xx000003DHP0AAO",
        "errors": []
    },
    {
        "success": True,
        "created": True,
        "id": "001xx000003DHP1AAO",
        "errors": []
    }
]
EXPECTED_QUERY = [
    {"Id": "001xx000003DHP0AAO", "AccountId": "ID-13",
        "Email": "contact1@example.com",
        "FirstName": "Bob", "LastName": "x"},
    {"Id": "001xx000003DHP1AAO", "AccountId": "ID-24",
        "Email": "contact2@example.com",
        "FirstName": "Alice", "LastName": "y"},
    {"Id": "001xx000003DHP0AAO", "AccountId": "ID-13",
        "Email": "contact1@example.com",
        "FirstName": "Bob", "LastName": "x"},
    {"Id": "001xx000003DHP1AAO", "AccountId": "ID-24",
        "Email": "contact2@example.com",
        "FirstName": "Alice", "LastName": "y"}
]

@pytest.mark.skip
@pytest.mark.asyncio
async def test_delete(sf_client, mock_httpx_client):
    _, mock_client, _ = mock_httpx_client
    operation = 'delete'
    body1 = {
        "apiVersion": 42.0,
        "concurrencyMode": "Parallel",
        "contentType": "JSON",
        "id": "Job-1",
        "object": "Contact",
        "operation": operation,
        "state": "Open"
    }
    body2 = {"id": "Batch-1", "jobId": "Job-1", "state": "Queued"}
    body3 = copy.deepcopy(body1)
    body3["state"] = "Closed"
    body4 = copy.deepcopy(body2)
    body4["state"] = "InProgress"
    body5 = copy.deepcopy(body2)
    body5["state"] = "Completed"
    body6 = [{
            "success": True,
            "created": True,
            "id": "001xx000003DHP0AAO",
            "errors": []
        }, {
            "success": True,
            "created": True,
            "id": "001xx000003DHP1AAO",
            "errors": []
        }]
    all_bodies = [body1, body2, body3, body4, body5, body6]
    responses = [
        httpx.Response(200, content=json.dumps(body)) for body in all_bodies
    ]
    mock_client.request.side_effect = mock.AsyncMock(side_effect=responses)
    data = [{
        'id': 'ID-1',
    }, {
        'id': 'ID-2',
    }]
    result = await sf_client.bulk.Contact.delete(data, wait=0.1)
    assert EXPECTED_RESULT == result

