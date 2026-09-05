"""Constants for the MobileKey integration."""

from typing import Final

DOMAIN: Final = "simonsvoss_mobilekey"

# Base URL of the SimonsVoss MobileKey cloud service.
API_URL_BASE: Final = "https://api.my-mobilekey.com/api/v10"

## Endpoints
# Endpoint for authentication (login) requests.
ENDPOINT_AUTH: Final = f"{API_URL_BASE}/auth/do"
# Endpoint returning the full locking system state in a single call.
ENDPOINT_SYSTEM_LOADLOCKING: Final = f"{API_URL_BASE}/lock-system/loadLockingSystem/"
# Endpoint executing lock commands (remote opening, audit trail readout).
ENDPOINT_PERFORMREQUEST: Final = f"{API_URL_BASE}/lock-system/performRequest"

AUTH_METHOD: Final = "GET"
USER_AGENT: Final = "MobileKey_iOS/2.8.0.2026082404"

## Cookies
# Session cookie issued by the cloud service after successful authentication.
COOKIE_AUTH: Final = "mk-auth"
# Cloudflare cookies.
COOKIE_CLOUDFLARE_BOTMANAGEMENT: Final = "__cf_bm"
COOKIE_CLOUDFLARE_USER_VID: Final = "_cfuvid"

# Default, minimum and maximum polling period of the cloud service, in
# seconds. The default stays close to the request rate of the mobile
# application; the minimum keeps the load on the cloud reasonable.
SCANINTERVAL_DEFAULT: Final = 60
SCANINTERVAL_MIN: Final = 30
SCANINTERVAL_MAX: Final = 3600
