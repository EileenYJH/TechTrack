import time
import random
import requests
from fake_useragent import UserAgent

_ua = UserAgent()

HEADERS_BASE = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}


def get_html(url: str, timeout: int = 15, retries: int = 3) -> str | None:
    headers = {**HEADERS_BASE, "User-Agent": _ua.random}
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt + random.random())
            else:
                print(f"[HTTP] Failed {url}: {e}")
    return None


def polite_sleep(min_s: float = 1.0, max_s: float = 3.0) -> None:
    time.sleep(random.uniform(min_s, max_s))
