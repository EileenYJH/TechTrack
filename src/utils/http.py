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


def get_html(url: str, timeout: int = 15, retries: int = 3, _verify: bool = True) -> str | None:
    headers = {**HEADERS_BASE, "User-Agent": _ua.random}
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout, verify=_verify)
            resp.raise_for_status()
            return resp.text
        except requests.exceptions.SSLError:
            if _verify:
                import urllib3
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                return get_html(url, timeout, retries, _verify=False)
            print(f"[HTTP] SSL error {url}")
            return None
        except requests.RequestException as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt + random.random())
            else:
                print(f"[HTTP] Failed {url}: {e}")
    return None


def polite_sleep(min_s: float = 1.0, max_s: float = 3.0) -> None:
    time.sleep(random.uniform(min_s, max_s))
