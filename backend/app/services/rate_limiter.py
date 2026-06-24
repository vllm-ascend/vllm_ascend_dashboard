import logging
import time
from collections import defaultdict

logger = logging.getLogger(__name__)

_rate_store: dict[str, list[float]] = defaultdict(list)

RATE_LIMITS = {
    "register": {"max_requests": 5, "window_seconds": 3600},
    "login": {"max_requests": 10, "window_seconds": 300},
}


def check_rate_limit(ip_address: str, action: str) -> None:
    config = RATE_LIMITS.get(action)
    if not config:
        return
    key = f"{ip_address}:{action}"
    now = time.time()
    window = config["window_seconds"]
    max_req = config["max_requests"]
    timestamps = _rate_store[key]
    timestamps[:] = [t for t in timestamps if now - t < window]
    if len(timestamps) >= max_req:
        raise ValueError(f"请求过于频繁，请在 {int(window / 60)} 分钟后重试")
    timestamps.append(now)
