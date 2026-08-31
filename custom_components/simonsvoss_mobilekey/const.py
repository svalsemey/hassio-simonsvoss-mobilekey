"""Constants for the MobileKey integration."""

from typing import Final

DOMAIN: Final = "mobilekey"

# Base URL of the SimonsVoss MobileKey cloud service.
API_BASE_URL: Final = "https://api.my-mobilekey.com/api/v10"

AUTH_ENDPOINT: Final = f"{API_BASE_URL}/auth/do"
AUTH_METHOD: Final = "GET"
AUTH_COOKIE: Final = "mk-auth"
USER_AGENT: Final = "ktor-client"
