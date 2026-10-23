"""Best-effort User-Agent labelling. Deliberately simple — no extra dependency."""

_BROWSERS = (
    ("Edg/", "Edge"),
    ("OPR/", "Opera"),
    ("Chrome/", "Chrome"),
    ("Firefox/", "Firefox"),
    ("Safari/", "Safari"),
    ("curl/", "curl"),
    ("HTTPie", "HTTPie"),
    ("python-httpx", "httpx"),
    ("PostmanRuntime", "Postman"),
)

_PLATFORMS = (
    ("iPhone", "iPhone"),
    ("iPad", "iPad"),
    ("Android", "Android"),
    ("Mac OS X", "macOS"),
    ("Macintosh", "macOS"),
    ("Windows", "Windows"),
    ("CrOS", "ChromeOS"),
    ("Linux", "Linux"),
)

UNKNOWN_DEVICE = "Unknown device"


def describe_device(user_agent: str | None) -> str:
    """Turn a User-Agent into something like 'Chrome on macOS'."""
    if not user_agent:
        return UNKNOWN_DEVICE

    # Order matters: Edge and Opera also advertise "Chrome".
    browser = next((name for token, name in _BROWSERS if token in user_agent), None)
    platform = next((name for token, name in _PLATFORMS if token in user_agent), None)

    if browser and platform:
        return f"{browser} on {platform}"
    return browser or platform or UNKNOWN_DEVICE
