"""Constants for the MobileKey integration."""

from typing import Final

DOMAIN: Final = "simonsvoss_mobilekey"

# Base URL of the SimonsVoss MobileKey cloud service.
API_BASE_URL: Final = "https://api.my-mobilekey.com/api/v10"

AUTH_ENDPOINT: Final = f"{API_BASE_URL}/auth/do"
AUTH_METHOD: Final = "GET"
AUTH_COOKIE: Final = "mk-auth"
CF_BM_COOKIE: Final = "__cf_bm"  # Name of the Cloudflare bot-management cookie, issued with an expiration.
USER_AGENT: Final = "ktor-client"
