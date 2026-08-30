"""Constants for the SimonsVoss MobileKey integration."""

DOMAIN = "mobilekey"

# Configuration keys
CONF_USERNAME = "username"
CONF_PASSWORD = "password"

# API endpoints
API_BASE_URL = "https://login.mobilekey.simonsvoss.com"
API_AUTH_ENDPOINT = "/api/login"
API_SMARTBRIDGES_ENDPOINT = "/api/smartbridges"
API_LOCKS_ENDPOINT = "/api/smartbridges/{smartbridge_id}/locks"
API_LOCK_CONTROL_ENDPOINT = "/api/smartbridges/{smartbridge_id}/locks/{lock_id}"

# Polling interval in seconds
DEFAULT_SCAN_INTERVAL = 30

# Lock states reported by the API
LOCK_STATE_LOCKED = "locked"
LOCK_STATE_UNLOCKED = "unlocked"
LOCK_STATE_UNKNOWN = "unknown"
