"""Constants for the MobileKey integration."""

from typing import Final

DOMAIN: Final = "simonsvoss_mobilekey"

# Option storing the HTTP User-Agent header sent to the cloud service.
CONF_USER_AGENT: Final = "user_agent"

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
# Default User-Agent header, mirroring the MobileKey mobile application.
# Overridable per config entry through the options flow.
USER_AGENT_DEFAULT: Final = "MobileKey_iOS/2.8.0.2026082404"

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

# Guest languages supported by Key4Friends invitations, as accepted by
# the cloud service.
KEY4FRIENDS_LANGUAGES: Final = ("en", "de", "fr", "it", "nl", "sv", "da")

## Service actions
SERVICE_KEY4FRIENDS_CREATE: Final = "key4friends_create"
SERVICE_KEY4FRIENDS_DELETE: Final = "key4friends_delete"
SERVICE_KEY4FRIENDS_GET: Final = "key4friends_get"
SERVICE_KEY4FRIENDS_LIST: Final = "key4friends_list"
SERVICE_KEY4FRIENDS_UPDATE: Final = "key4friends_update"

## Field names shared by the service actions and the options flow.
ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"
ATTR_LOCKS: Final = "locks"
ATTR_LOCK_NAMES: Final = "lock_names"
ATTR_VALID_FROM: Final = "valid_from"
ATTR_VALID_TO: Final = "valid_to"