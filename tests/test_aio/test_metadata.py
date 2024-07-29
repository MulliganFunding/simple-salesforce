import aiofiles
import re

import pytest
from pytest_httpx import HTTPXMock

from simple_salesforce.exceptions import SalesforceGeneralError


SOAP_SCHEMAS_PAT = re.compile(r"http://schemas.xmlsoap.org/.*")
SOAP_SFORCE_PAT = re.compile(r"http://soap\.sforce\.com/.*")


@pytest.fixture
def assert_all_responses_were_requested() -> bool:
    # Disable checking httpx_mock for unrequested responses
    return False


@pytest.fixture()
def mdapi(sf_client):
    return sf_client.mdapi


@pytest.fixture()
async def mdapi_type(mdapi, httpx_mock, constants, urls):
    httpx_mock.add_response(
        url=urls["soap_url_pat"],
        text=constants["LOGIN_RESPONSE_SUCCESS"],
    )
    httpx_mock.add_response(
        status_code=200,
        method="POST",
        url=urls["soap_server_url"],
    )
    httpx_mock.add_response(
        status_code=200,
        method="POST",
        url=SOAP_SCHEMAS_PAT,
    )
    httpx_mock.add_response(
        status_code=200,
        method="POST",
        url=SOAP_SFORCE_PAT,
    )
    # return using arbitrary metadata type
    return mdapi.LeadConvertSettings


# # # # # # # # # # # # # # # # # # # # # #
#
# AsyncMetadataType Tests
#
# # # # # # # # # # # # # # # # # # # # # #
@pytest.mark.parametrize(
    "handler",
    (
        "create",
        "update",
        "upsert",
        "delete",
    ),
)
async def test_crud_handlers(handler, httpx_mock, fixture_loader, mdapi, mdapi_type):
    httpx_mock.add_response(
        status_code=200,
        method="POST",
        url=re.compile(f"{mdapi.metadata_url}.*"),
        text=await fixture_loader("metadata_create.xml"),
    )
    async_func = getattr(mdapi_type, handler)

    # Should be able to successfully call the handler without exception (sees "success => true")
    result = await async_func(["LeadConvertSettings"])
    assert result is None


async def test_read(httpx_mock, fixture_loader, mdapi, mdapi_type):
    httpx_mock.add_response(
        status_code=200,
        method="POST",
        url=re.compile(f"{mdapi.metadata_url}.*"),
        text=await fixture_loader("metadata_read.xml"),
    )
    result = await mdapi_type.read(["LeadConvertSettings"])
    assert result["fullName"] == "LeadConvertSettings"
    assert result["allowOwnerChange"] is True
    assert (
        result["objectMapping"] and len(result["objectMapping"]) > 0
    )  # a populated list


async def test_rename(httpx_mock, fixture_loader, mdapi, mdapi_type):
    httpx_mock.add_response(
        status_code=200,
        method="POST",
        url=re.compile(f"{mdapi.metadata_url}.*"),
        text=await fixture_loader("metadata_create.xml"),
    )
    # Should be able to successfully call the handler without exception (sees "success => true")
    result = await mdapi_type.rename("NewName", "OldName")
    assert result is None


async def test_describe(httpx_mock, fixture_loader, mdapi, mdapi_type):
    httpx_mock.add_response(
        status_code=200,
        method="POST",
        url=re.compile(f"{mdapi.metadata_url}.*"),
        text=await fixture_loader("metadata_create.xml"),
    )
    result = await mdapi_type.describe()
    assert "apiReadable" in result


# # # # # # # # # # # # # # # # # # # # # #
#
# AsyncSfdcMetadataApi Tests
#
# # # # # # # # # # # # # # # # # # # # # #
async def test_md_describe(
    fixture_loader,
    httpx_mock: HTTPXMock,
    mdapi,
):
    httpx_mock.add_response(
        status_code=200,
        method="POST",
        url=re.compile(f"{mdapi.metadata_url}.*"),
        text=await fixture_loader("metadata_read.xml"),
    )
    await mdapi.describe_metadata()


# These deploy tests are duplicated from test_api.py
async def test_md_deploy_success(
    httpx_mock: HTTPXMock,
    mdapi,
):
    """Test method for metadata deployment"""
    mock_response = (
        '<?xml version="1.0" '
        'encoding="UTF-8"?><soapenv:Envelope '
        'xmlns:soapenv="http://schemas.xmlsoap.org/soap'
        '/envelope/" '
        'xmlns="http://soap.sforce.com/2006/04/metadata'
        '"><soapenv:Body><deployResponse><result><done'
        ">false</done><id>0Af3B00001CMyfASAT</id><state"
        ">Queued</state></result></deployResponse></soapenv"
        ":Body></soapenv:Envelope>"
    )

    httpx_mock.add_response(content=mock_response, status_code=200)

    async with aiofiles.tempfile.NamedTemporaryFile("wb+") as fl:
        await fl.write(b"Line1\n Line2")
        await fl.seek(0)
        asyncId, state = await mdapi.deploy(fl.name, sandbox=False)
    assert asyncId == "0Af3B00001CMyfASAT"
    assert state == "Queued"

    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    req1 = requests[0]

    assert req1.method == "POST"
    assert str(req1.url) == f"{mdapi.metadata_url}deployRequest"


async def test_md_deploy_success_open(
    httpx_mock: HTTPXMock,
    mdapi,
):
    """Test method for metadata deployment"""
    mock_response = (
        '<?xml version="1.0" '
        'encoding="UTF-8"?><soapenv:Envelope '
        'xmlns:soapenv="http://schemas.xmlsoap.org/soap'
        '/envelope/" '
        'xmlns="http://soap.sforce.com/2006/04/metadata'
        '"><soapenv:Body><deployResponse><result><done'
        ">false</done><id>0Af3B00001CMyfASAT</id><state"
        ">Queued</state></result></deployResponse></soapenv"
        ":Body></soapenv:Envelope>"
    )
    httpx_mock.add_response(content=mock_response, status_code=200)

    async with aiofiles.tempfile.NamedTemporaryFile("wb+") as fl:
        await fl.write(b"Line1\n Line2")
        await fl.seek(0)
        asyncId, state = await mdapi.deploy(fl.name, sandbox=False)
    assert asyncId == "0Af3B00001CMyfASAT"
    assert state == "Queued"

    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    req1 = requests[0]

    assert req1.method == "POST"
    assert str(req1.url) == f"{mdapi.metadata_url}deployRequest"


async def test_md_deploy_failed_status_code(
    httpx_mock: HTTPXMock,
    mdapi,
):
    """Test method for metadata deployment on Failure"""

    httpx_mock.add_response(
        status_code=2599,
        method="POST",
        url=re.compile(f"{mdapi.metadata_url}deployRequest"),
        content=b"Unrecognized Error",
    )

    async with aiofiles.tempfile.NamedTemporaryFile("wb+") as fl:
        await fl.write(b"Line1\n Line2")
        await fl.seek(0)
        with pytest.raises(SalesforceGeneralError):
            await mdapi.deploy(fl.name, sandbox=False)
