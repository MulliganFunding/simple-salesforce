"""Tests for login.py"""

import os
import re
from urllib.parse import parse_qs, urlparse
import warnings

import pytest
from pytest_httpx import HTTPXMock

from simple_salesforce.api import DEFAULT_API_VERSION
from simple_salesforce.exceptions import SalesforceAuthenticationFailed
from simple_salesforce.aio.login import AsyncSalesforceLogin


PARENT_DIR = os.path.dirname(os.path.dirname(__file__))


async def test_default_domain_success(constants, urls, httpx_mock: HTTPXMock):
    """Test login for default domain"""

    httpx_mock.add_response(
        status_code=200,
        url=urls["soap_url_pat"],
        text=constants["LOGIN_RESPONSE_SUCCESS"],
    )

    (session_id, instance_url) = await AsyncSalesforceLogin(
        username="foo@bar.com",
        password="password",
        security_token="token",
    )
    assert session_id == constants["SESSION_ID"]
    assert instance_url == urlparse(constants["INSTANCE_URL"]).netloc
    requests = httpx_mock.get_requests()
    assert len(requests) == 1

    assert requests[0].method == "POST"
    assert str(requests[0].url).startswith(urls["soap_url"])
    assert "SOAPAction" in requests[0].headers
    assert requests[0].headers["SOAPAction"] == "login"


async def test_custom_domain_success(constants, httpx_mock: HTTPXMock):
    """Test login for custom domain"""
    url = re.compile(r"https://testdomain.my.salesforce.com/services/Soap/u/.*")

    httpx_mock.add_response(
        status_code=200, url=url, text=constants["LOGIN_RESPONSE_SUCCESS"]
    )

    (session_id, instance_url) = await AsyncSalesforceLogin(
        username="foo@bar.com",
        password="password",
        domain="testdomain.my",
    )
    assert session_id == constants["SESSION_ID"]
    assert instance_url == urlparse(constants["INSTANCE_URL"]).netloc
    requests = httpx_mock.get_requests()
    assert len(requests) == 1

    assert requests[0].method == "POST"
    SOAP_API_URL = (
        f"https://testdomain.my.salesforce.com/services/Soap/u/{DEFAULT_API_VERSION}"
    )
    assert str(requests[0].url).startswith(SOAP_API_URL)
    assert "SOAPAction" in requests[0].headers
    assert requests[0].headers["SOAPAction"] == "login"


async def test_custom_domain_soap_failure(urls, httpx_mock: HTTPXMock):
    """Test login for custom domain"""
    fail_result = (
        '<?xml version="1.0" encoding="UTF-8"?><soapenv:Envelope '
        'xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
        'xmlns:sf="urn:fault.partner.soap.sforce.com" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        "<soapenv:Body><soapenv:Fault><faultcode>INVALID_LOGIN</faultcode>"
        "<faultstring>INVALID_LOGIN: Invalid username, password, "
        "security token; or user locked out.</faultstring><detail>"
        '<sf:LoginFault xsi:type="sf:LoginFault"><sf:exceptionCode>'
        "INVALID_LOGIN</sf:exceptionCode><sf:exceptionMessage>Invalid "
        "username, password, security token; or user locked out."
        "</sf:exceptionMessage></sf:LoginFault></detail></soapenv:Fault>"
        "</soapenv:Body></soapenv:Envelope>"
    )

    httpx_mock.add_response(
        status_code=500, url=urls["soap_url_pat"], text=fail_result
    )

    with pytest.raises(SalesforceAuthenticationFailed):
        await AsyncSalesforceLogin(
            username="foo@bar.com",
            password="password",
            security_token="token",
        )
    requests = httpx_mock.get_requests()
    assert len(requests) == 1

    assert requests[0].method == "POST"
    assert str(requests[0].url).startswith(urls["soap_url"])
    assert "SOAPAction" in requests[0].headers
    assert requests[0].headers["SOAPAction"] == "login"


@pytest.fixture()
def sample_key_filepath():
    """Path to sample-key fixture"""
    return os.path.join(PARENT_DIR, "sample-key.pem")


@pytest.fixture()
def sample_key(sample_key_filepath):
    """File-handle in bytes for sample-key fixture"""
    with open(sample_key_filepath, "rb") as key_file:
        return key_file.read()


async def test_token_login_success_with_key_file(
    sample_key_filepath, urls, constants, httpx_mock: HTTPXMock
):
    """Test a successful JWT Token login with a key file"""
    httpx_mock.add_response(
        status_code=200,
        url=urls["oauth_token_url_pat"],
        text=constants["TOKEN_LOGIN_RESPONSE_SUCCESS"],
    )

    (session_id, instance_url) = await AsyncSalesforceLogin(
        username="foo@bar.com",
        consumer_key="12345.abcde",
        privatekey_file=sample_key_filepath,
    )
    assert session_id == constants["SESSION_ID"]
    assert instance_url == urlparse(constants["INSTANCE_URL"]).netloc

    requests = httpx_mock.get_requests()
    assert len(requests) == 1

    assert requests[0].method == "POST"
    assert str(requests[0].url).startswith(urls["oauth_token_url"])
    parsed_data = parse_qs(requests[0].content)

    assert parsed_data[b"grant_type"] == (
        [b"urn:ietf:params:oauth:grant-type:jwt-bearer"]
    )


async def test_token_login_success_with_key_string(
    sample_key, urls, constants, httpx_mock: HTTPXMock
):
    """Test a successful JWT Token login with a private key"""
    httpx_mock.add_response(
        status_code=200,
        url=urls["oauth_token_url_pat"],
        text=constants["TOKEN_LOGIN_RESPONSE_SUCCESS"],
    )

    (session_id, instance_url) = await AsyncSalesforceLogin(
        username="foo@bar.com",
        consumer_key="12345.abcde",
        privatekey=sample_key.decode(),
    )

    assert session_id == constants["SESSION_ID"]
    assert instance_url == urlparse(constants["INSTANCE_URL"]).netloc

    requests = httpx_mock.get_requests()
    assert len(requests) == 1

    assert requests[0].method == "POST"
    assert str(requests[0].url).startswith(urls["oauth_token_url"])
    parsed_data = parse_qs(requests[0].content)

    assert parsed_data[b"grant_type"] == (
        [b"urn:ietf:params:oauth:grant-type:jwt-bearer"]
    )


async def test_token_login_with_instance_url(
    sample_key_filepath, urls, constants, httpx_mock: HTTPXMock
):
    """Test a successful JWT Token login with an instance_url and a domain"""
    httpx_mock.add_response(
        status_code=200,
        url=re.compile(r"https://anothertestdomain\.my.*"),
        text=constants["TOKEN_LOGIN_RESPONSE_SUCCESS"],
    )

    (session_id, instance_url) = await AsyncSalesforceLogin(
        username="foo@bar.com",
        consumer_key="12345.abcde",
        domain="testdomain.my",
        instance_url="anothertestdomain.my.salesforce.com",
        privatekey_file=sample_key_filepath,
    )

    assert session_id == constants["SESSION_ID"]
    assert instance_url == urlparse(constants["INSTANCE_URL"]).netloc

    requests = httpx_mock.get_requests()
    assert len(requests) == 1

    assert requests[0].method == "POST"
    assert str(requests[0].url).startswith("https://anothertestdomain.my.salesforce.com")
    parsed_data = parse_qs(requests[0].content)

    assert parsed_data[b"grant_type"] == (
        [b"urn:ietf:params:oauth:grant-type:jwt-bearer"]
    )


async def test_token_login_success_with_key_bytes(
    sample_key, urls, constants, httpx_mock: HTTPXMock
):
    """Test a successful JWT Token login with a private key"""
    httpx_mock.add_response(
        status_code=200,
        url=urls["oauth_token_url_pat"],
        text=constants["TOKEN_LOGIN_RESPONSE_SUCCESS"],
    )

    (session_id, instance_url) = await AsyncSalesforceLogin(
        username="foo@bar.com",
        consumer_key="12345.abcde",
        privatekey=sample_key,
    )

    assert session_id == constants["SESSION_ID"]
    assert instance_url == urlparse(constants["INSTANCE_URL"]).netloc
    requests = httpx_mock.get_requests()
    assert len(requests) == 1

    assert requests[0].method == "POST"
    assert str(requests[0].url).startswith(urls["oauth_token_url"])
    parsed_data = parse_qs(requests[0].content)

    assert parsed_data[b"grant_type"] == (
        [b"urn:ietf:params:oauth:grant-type:jwt-bearer"]
    )


async def test_token_login_failure(urls, httpx_mock: HTTPXMock, sample_key_filepath):
    """Test login for custom domain"""
    httpx_mock.add_response(
        status_code=400,
        url=urls["oauth_token_url_pat"],
        json={
            "error": "invalid_client_id",
            "error_description": "client identifier invalid",
        },
    )

    with pytest.raises(SalesforceAuthenticationFailed):
        await AsyncSalesforceLogin(
            username="foo@bar.com",
            consumer_key="12345.abcde",
            privatekey_file=sample_key_filepath,
        )
    requests = httpx_mock.get_requests()
    assert len(requests) == 1

    assert requests[0].method == "POST"
    assert str(requests[0].url).startswith(urls["oauth_token_url"])
    parsed_data = parse_qs(requests[0].content)

    assert parsed_data[b"grant_type"] == (
        [b"urn:ietf:params:oauth:grant-type:jwt-bearer"]
    )


async def test_token_login_failure_with_warning(
    urls, httpx_mock: HTTPXMock, constants, sample_key_filepath
):
    """Test login failure with warning"""
    httpx_mock.add_response(
        status_code=400,
        url=urls["oauth_token_url_pat"],
        json={
            "error": "invalid_grant",
            "error_description": "user hasn't approved this consumer",
        },
    )

    with warnings.catch_warnings(record=True) as warning:
        with pytest.raises(SalesforceAuthenticationFailed):
            await AsyncSalesforceLogin(
                username="foo@bar.com",
                consumer_key="12345.abcde",
                privatekey_file=sample_key_filepath,
            )
    requests = httpx_mock.get_requests()
    assert len(requests) == 1

    assert requests[0].method == "POST"
    assert str(requests[0].url).startswith(urls["oauth_token_url"])
    parsed_data = parse_qs(requests[0].content)

    assert parsed_data[b"grant_type"] == (
        [b"urn:ietf:params:oauth:grant-type:jwt-bearer"]
    )

    assert len(warning) >= 1
    assert issubclass(warning[-1].category, UserWarning)
    assert str(warning[-1].message) == constants["TOKEN_WARNING"]


async def test_connected_app_login_success(constants, urls, httpx_mock: HTTPXMock):
    """Test a successful connected app login with a key file"""

    httpx_mock.add_response(
        status_code=200,
        url=urls["oauth_token_url_pat"],
        text=constants["TOKEN_LOGIN_RESPONSE_SUCCESS"],
    )

    (session_id, instance_url) = await AsyncSalesforceLogin(
        username="foo@bar.com",
        password="password",
        consumer_key="12345.abcde",
        consumer_secret="12345.abcde",
    )
    assert session_id == constants["SESSION_ID"]
    assert instance_url == urlparse(constants["INSTANCE_URL"]).netloc
    requests = httpx_mock.get_requests()
    assert len(requests) == 1

    assert requests[0].method == "POST"
    assert str(requests[0].url).startswith(urls["oauth_token_url"])
    parsed_data = parse_qs(requests[0].content)

    assert parsed_data[b"grant_type"] == [b"password"]


async def test_connected_app_login_failure(urls, httpx_mock: HTTPXMock):
    """Test a failed connected app login"""
    httpx_mock.add_response(
        status_code=400,
        url=urls["oauth_token_url_pat"],
        json={
            "error": "invalid_grant",
            "error_description": "client identifier invalid",
        },
    )

    with pytest.raises(SalesforceAuthenticationFailed):
        await AsyncSalesforceLogin(
            username="myemail@example.com.sandbox",
            password="password",
            consumer_key="12345.abcde",
            consumer_secret="12345.abcde",
        )
    requests = httpx_mock.get_requests()
    assert len(requests) == 1

    assert requests[0].method == "POST"
    assert str(requests[0].url).startswith(urls["oauth_token_url"])
    parsed_data = parse_qs(requests[0].content)

    assert parsed_data[b"grant_type"] == [b"password"]
    assert parsed_data[b"client_id"] == [b"12345.abcde"]


async def test_connected_app_client_credentials_login_success(urls, constants, httpx_mock: HTTPXMock):
    """Test a successful connected app login with client credentials"""
    login_args = {
        "consumer_key": "12345.abcde",
        "consumer_secret": "12345.abcde",
        "domain": "testdomain.my"
    }

    httpx_mock.add_response(
        status_code=200,
        url=urls["test_domain_pat"],
        text=constants["TOKEN_LOGIN_RESPONSE_SUCCESS"],
    )
    (session_id, instance_url) = await AsyncSalesforceLogin(**login_args)
    assert session_id == constants["SESSION_ID"]
    assert instance_url == urlparse(constants["INSTANCE_URL"]).netloc

    requests = httpx_mock.get_requests()
    assert len(requests) == 1

    assert str(requests[0].url).startswith(urls["test_domain"])
    parsed_data = parse_qs(requests[0].content)

    assert parsed_data[b"grant_type"] == [b"client_credentials"]


async def test_connected_app_client_credentials_login_failure(urls, httpx_mock: HTTPXMock):
    """Test a failed connected app login"""

    httpx_mock.add_response(
        status_code=400,
        url=urls["test_domain_pat"],
        json={
            "error": "invalid_grant",
            "error_description": "client identifier invalid",
        },
    )

    login_args = {
        "consumer_key": "12345.abcde",
        "consumer_secret": "12345.abcde",
        "domain": "testdomain.my"
    }
    with pytest.raises(SalesforceAuthenticationFailed):
        await AsyncSalesforceLogin(**login_args)

    requests = httpx_mock.get_requests()
    assert len(requests) == 1

    assert str(requests[0].url).startswith(urls["test_domain"])
    parsed_data = parse_qs(requests[0].content)

    assert parsed_data[b"grant_type"] == [b"client_credentials"]
