"""
scraper.py
==========
Headless-Selenium OSINT layer for Secure-OSINT-FaceID.

This module is deliberately isolated from the vision code. It takes an image or
a query, drives a headless browser against *public* sources, and returns
structured results. It never talks to MediaPipe/DeepFace and never touches the
web server directly.

Ethical scope
-------------
This tool is intended for authorized security research, testing against your own
assets, and consenting-subject investigations. It uses only public search
surfaces, honors a conservative rate limit, and sets a truthful User-Agent.
It intentionally does NOT integrate any "identify a stranger from their face"
service — face-of-stranger identification is out of scope by design.

Dependencies: selenium (Chrome/Chromium + a matching driver on PATH, or
Selenium Manager which resolves the driver automatically for recent Selenium).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import WebDriverException


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #
@dataclass
class OSINTHit:
    """A single result surfaced by a lookup."""

    title: str
    url: str
    snippet: str = ""
    source: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class OSINTScraper:
    """
    Thin, respectful wrapper around a headless Chromium session.

    Use it as a context manager so the browser is always torn down::

        with OSINTScraper() as osint:
            hits = osint.web_search("example query")

    Parameters
    ----------
    headless:
        Run without a visible window (default True).
    rate_limit_seconds:
        Minimum spacing between navigations — be a good citizen.
    page_load_timeout:
        Hard cap on any single page load.
    user_agent:
        Sent verbatim; keep it honest.
    """

    DEFAULT_UA = "Secure-OSINT-FaceID/1.0 (authorized-research; +contact-admin)"

    def __init__(
        self,
        headless: bool = True,
        rate_limit_seconds: float = 2.0,
        page_load_timeout: int = 30,
        user_agent: Optional[str] = None,
        window_size: tuple[int, int] = (1280, 900),
    ):
        self.headless = headless
        self.rate_limit_seconds = rate_limit_seconds
        self.page_load_timeout = page_load_timeout
        self.user_agent = user_agent or self.DEFAULT_UA
        self.window_size = window_size

        self._driver: Optional[webdriver.Chrome] = None
        self._last_request_ts = 0.0

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        """Launch the headless browser (idempotent)."""
        if self._driver is not None:
            return

        opts = Options()
        if self.headless:
            opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument(f"--window-size={self.window_size[0]},{self.window_size[1]}")
        opts.add_argument(f"--user-agent={self.user_agent}")
        # Reduce automation fingerprint noise without hiding that we're a bot.
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)

        self._driver = webdriver.Chrome(options=opts)
        self._driver.set_page_load_timeout(self.page_load_timeout)

    def close(self) -> None:
        if self._driver is not None:
            try:
                self._driver.quit()
            finally:
                self._driver = None

    def __enter__(self) -> "OSINTScraper":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _throttle(self) -> None:
        """Enforce the minimum spacing between navigations."""
        elapsed = time.monotonic() - self._last_request_ts
        wait = self.rate_limit_seconds - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request_ts = time.monotonic()

    def _navigate(self, url: str) -> None:
        if self._driver is None:
            raise RuntimeError("Scraper not started. Call start() or use as a context manager.")
        self._throttle()
        self._driver.get(url)

    # ------------------------------------------------------------------ #
    # Public lookups
    # ------------------------------------------------------------------ #
    def web_search(self, query: str, max_results: int = 10) -> list[OSINTHit]:
        """
        Run a public web search and return the organic result links.

        Uses DuckDuckGo's HTML endpoint, which is scraping-friendly and needs no
        API key or JavaScript. Great baseline for name/handle/keyword pivots.
        """
        self._navigate(f"https://html.duckduckgo.com/html/?q={quote_plus(query)}")
        hits: list[OSINTHit] = []
        try:
            nodes = self._driver.find_elements(By.CSS_SELECTOR, "div.result")
            for node in nodes:
                if len(hits) >= max_results:
                    break
                try:
                    link = node.find_element(By.CSS_SELECTOR, "a.result__a")
                except WebDriverException:
                    continue
                title = link.text.strip()
                url = link.get_attribute("href") or ""
                snippet = ""
                try:
                    snippet = node.find_element(By.CSS_SELECTOR, "a.result__snippet").text.strip()
                except WebDriverException:
                    pass
                if title and url:
                    hits.append(OSINTHit(title=title, url=url, snippet=snippet, source="duckduckgo"))
        except WebDriverException as exc:
            print(f"[OSINTScraper] web_search failed: {exc}")
        return hits

    def reverse_image_search(self, image_path: str, max_results: int = 10) -> list[OSINTHit]:
        """
        Kick off a reverse-image lookup for a local file.

        Fully automated reverse-image search across engines is brittle and
        changes often, so this returns the *upload targets* plus any links the
        results page exposes. Treat it as a launch pad rather than a guarantee.

        Intended for images you own or are authorized to investigate.
        """
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        # Google Lens upload surface. We open it and expose the file input so a
        # caller can attach the image; some deployments block headless uploads,
        # which is why results are best-effort.
        self._navigate("https://lens.google.com/")
        hits: list[OSINTHit] = []
        try:
            file_inputs = self._driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
            if file_inputs:
                file_inputs[0].send_keys(str(path.resolve()))
                time.sleep(3)  # allow the results page to populate
            for a in self._driver.find_elements(By.CSS_SELECTOR, "a[href^='http']"):
                if len(hits) >= max_results:
                    break
                url = a.get_attribute("href") or ""
                title = (a.text or "").strip()
                if url and title and "google.com" not in url:
                    hits.append(OSINTHit(title=title, url=url, source="google-lens"))
        except WebDriverException as exc:
            print(f"[OSINTScraper] reverse_image_search failed: {exc}")
        return hits

    def fetch_page_text(self, url: str, max_chars: int = 5000) -> str:
        """Load a URL and return its visible text (bounded)."""
        self._navigate(url)
        try:
            body = self._driver.find_element(By.TAG_NAME, "body")
            return body.text[:max_chars]
        except WebDriverException as exc:
            print(f"[OSINTScraper] fetch_page_text failed: {exc}")
            return ""
