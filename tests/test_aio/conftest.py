"""
Common fixtures for tests in this directory
"""
import os
import pathlib
import re
from unittest import mock

import aiofiles
import pytest

from simple_salesforce.aio import AsyncSalesforce


SESSION_ID = "12345"
INSTANCE_URL = "https://na15.salesforce.com"
TOKEN_ID = "https://na15.salesforce.com/id/00Di0000000icUB/0DFi00000008UYO"
METADATA_URL = "https://na15.salesforce.com/services/Soap/m/29.0/00Di0000000icUB"
SERVER_URL = (
    "https://na15.salesforce.com/services/Soap/c/29.0/00Di0000000icUB/0DFi00000008UYO"
)
PROXIES = {
    "http": "http://10.10.1.10:3128",
    "https": "http://10.10.1.10:1080",
}

LOGIN_RESPONSE_SUCCESS = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns="urn:enterprise.soap.sforce.com" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
   <soapenv:Body>
      <loginResponse>
         <result>
            <metadataServerUrl>{METADATA_URL}</metadataServerUrl>
            <passwordExpired>false</passwordExpired>
            <sandbox>false</sandbox>
            <serverUrl>{SERVER_URL}</serverUrl>
            <sessionId>{SESSION_ID}</sessionId>
            <userId>005i0000002MUqLAAW</userId>
            <userInfo>
               <accessibilityMode>false</accessibilityMode>
               <currencySymbol>$</currencySymbol>
               <orgAttachmentFileSizeLimit>5242880</orgAttachmentFileSizeLimit>
               <orgDefaultCurrencyIsoCode>USD</orgDefaultCurrencyIsoCode>
               <orgDisallowHtmlAttachments>false</orgDisallowHtmlAttachments>
               <orgHasPersonAccounts>false</orgHasPersonAccounts>
               <organizationId>00Di0000000icUBEAY</organizationId>
               <organizationMultiCurrency>false</organizationMultiCurrency>
               <organizationName>salesforce.com</organizationName>
               <profileId>00ei0000001CMKcAAO</profileId>
               <roleId xsi:nil="true" />
               <sessionSecondsValid>7200</sessionSecondsValid>
               <userDefaultCurrencyIsoCode xsi:nil="true" />
               <userEmail>you@yourdomain.com</userEmail>
               <userFullName>Wade Wegner</userFullName>
               <userId>1234</userId>
               <userLanguage>en_US</userLanguage>
               <userLocale>en_US</userLocale>
               <userName>you@yourdomain.com</userName>
               <userTimeZone>America/Los_Angeles</userTimeZone>
               <userType>Standard</userType>
               <userUiSkin>Theme3</userUiSkin>
            </userInfo>
         </result>
      </loginResponse>
   </soapenv:Body>
</soapenv:Envelope>
"""

TOKEN_LOGIN_RESPONSE_SUCCESS = f"""{{
    "access_token": "{SESSION_ID}",
    "scope": "web api",
    "instance_url": "{INSTANCE_URL}",
    "id": "{TOKEN_ID}",
    "token_type": "Bearer"
}}"""

TOKEN_WARNING = """
    If your connected app policy is set to "All users may
    self-authorize", you may need to authorize this
    application first. Browse to
    https://login.salesforce.com/services/oauth2/authorize?response_type=code&client_id=12345.abcde&redirect_uri=<approved URI>
    in order to Allow Access. Check first to ensure you have a valid
    <approved URI>."""

ORGANIZATION_LIMITS_RESPONSE = {
    "ConcurrentAsyncGetReportInstances": {"Max": 200, "Remaining": 200},
    "ConcurrentSyncReportRuns": {"Max": 20, "Remaining": 20},
    "DailyApiRequests": {"Max": 15000, "Remaining": 14998},
    "DailyAsyncApexExecutions": {"Max": 250000, "Remaining": 250000},
    "DailyBulkApiRequests": {"Max": 5000, "Remaining": 5000},
    "DailyDurableGenericStreamingApiEvents": {"Max": 10000, "Remaining": 10000},
    "DailyDurableStreamingApiEvents": {"Max": 10000, "Remaining": 10000},
    "DailyGenericStreamingApiEvents": {"Max": 10000, "Remaining": 10000},
    "DailyStreamingApiEvents": {"Max": 10000, "Remaining": 10000},
    "DailyWorkflowEmails": {"Max": 390, "Remaining": 390},
    "DataStorageMB": {"Max": 5, "Remaining": 5},
    "DurableStreamingApiConcurrentClients": {"Max": 20, "Remaining": 20},
    "FileStorageMB": {"Max": 20, "Remaining": 20},
    "HourlyAsyncReportRuns": {"Max": 1200, "Remaining": 1200},
    "HourlyDashboardRefreshes": {"Max": 200, "Remaining": 200},
    "HourlyDashboardResults": {"Max": 5000, "Remaining": 5000},
    "HourlyDashboardStatuses": {"Max": 999999999, "Remaining": 999999999},
    "HourlyODataCallout": {"Max": 10000, "Remaining": 9999},
    "HourlySyncReportRuns": {"Max": 500, "Remaining": 500},
    "HourlyTimeBasedWorkflow": {"Max": 50, "Remaining": 50},
    "MassEmail": {"Max": 10, "Remaining": 10},
    "SingleEmail": {"Max": 15, "Remaining": 15},
    "StreamingApiConcurrentClients": {"Max": 20, "Remaining": 20},
}

BULK_HEADERS = {
    "Content-Type": "application/json",
    "X-SFDC-Session": SESSION_ID,
    "X-PrettyPrint": "1",
}

BULK2_HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {SESSION_ID}",
    "X-PrettyPrint": "1",
}

ALL_CONSTANTS = {
    "LOGIN_RESPONSE_SUCCESS": LOGIN_RESPONSE_SUCCESS,
    "TOKEN_LOGIN_RESPONSE_SUCCESS": TOKEN_LOGIN_RESPONSE_SUCCESS,
    "TOKEN_WARNING": TOKEN_WARNING,
    "ORGANIZATION_LIMITS_RESPONSE": ORGANIZATION_LIMITS_RESPONSE,
    "BULK_HEADERS": BULK_HEADERS,
    "BULK2_HEADERS": BULK2_HEADERS,
    "SESSION_ID": "12345",
    "INSTANCE_URL": "https://na15.salesforce.com",
    "TOKEN_ID": "https://na15.salesforce.com/id/00Di0000000icUB/0DFi00000008UYO",
    "METADATA_URL": "https://na15.salesforce.com/services/Soap/m/29.0/00Di0000000icUB",
    "SERVER_URL": "https://na15.salesforce.com/services/Soap/c/29.0/00Di0000000icUB/0DFi00000008UYO",
    "PROXIES": {
        "http://": "http://10.10.1.10:3128",
        "https://": "http://10.10.1.10:1080",
    },
}

test_dir = os.path.dirname(__file__)
fixtures = pathlib.Path(test_dir) / "fixtures"


@pytest.fixture()
def fixtures_dir():
    """should be a ./fixtures dir in same directory as this conftest.py"""
    return fixtures


@pytest.fixture()
def fixture_loader(fixtures_dir):
    """Build a function to load an XML fixture"""
    async def loader(fixture_name):
        async with aiofiles.open(str(fixtures_dir / fixture_name), "r") as fixture:
            return await fixture.read()
    return loader


@pytest.fixture()
def constants():
    """Constants defined above as a pytest fixture"""
    return ALL_CONSTANTS


# pylint: disable=unused-argument
# pylint: disable=redefined-outer-name
@pytest.fixture()
def sf_client(constants):
    """Simple fixture for crafting the client used below"""
    client = AsyncSalesforce(
        session_id=constants["SESSION_ID"],
        proxies=constants["PROXIES"]
    )

    client.login_refresh = mock.AsyncMock(return_value=(constants["SESSION_ID"], "test"))
    client.headers = {}
    client.base_url = "https://localhost/"
    client.metadata_url = "https://localhost/metadata/"
    client.bulk_url = "https://localhost/async/"
    client.apex_url = "https://localhost/apexrest/"
    client.tooling_url = "https://localhost/tooling/"
    return client


TEST_DOMAIN = "https://testdomain.my.salesforce.com"
SOAP_URL = "https://login.salesforce.com/services/Soap/u/"
OAUTH_TOKEN_URL = "https://login.salesforce.com/services/oauth2/token"


# Regex patterns for matching URLs
OATH_TOKEN_URL_PAT = re.compile(r"https://login\.salesforce\.com/services/oauth2/token/?.*")
SOAP_URL_PAT = re.compile(r"https://login\.salesforce\.com/services/Soap/[u|m]/?.*")
TEST_DOMAIN_PAT = re.compile(r"https://testdomain\.my.*")
SOAP_SERVER_URL_PAT = re.compile(r"https://na15\.salesforce\.com.*")


@pytest.fixture()
def urls():
    return {
        "metadata_url": METADATA_URL,
        "soap_server_url": SOAP_SERVER_URL_PAT,
        "soap_url": SOAP_URL,
        "oauth_token_url": OAUTH_TOKEN_URL,
        "soap_url_pat": SOAP_URL_PAT,
        "oauth_token_url_pat": OATH_TOKEN_URL_PAT,
        "test_domain": TEST_DOMAIN,
        "test_domain_pat": TEST_DOMAIN_PAT,
    }


@pytest.fixture()
def test_domain():
    return TEST_DOMAIN


@pytest.fixture()
def soap_login_url():
    return SOAP_URL


@pytest.fixture()
def oauth_token_url():
    return OAUTH_TOKEN_URL


@pytest.fixture()
def soap_url_pat():
    return SOAP_URL_PAT


@pytest.fixture()
def oauth_token_url_pat():
    return OATH_TOKEN_URL_PAT


@pytest.fixture()
def test_domain_pat():
    return TEST_DOMAIN_PAT

