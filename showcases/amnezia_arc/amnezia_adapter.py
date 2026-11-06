"""Amnezia Hosting (my.amnezia.host) client adapter.

Provides web session automation for logging in, querying account details and balance,
and listing available VPS hardware tiers.
"""

from __future__ import annotations

import http.cookiejar
import logging
import os
import pathlib
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal

logger = logging.getLogger(__name__)

BASE_URL = "https://my.amnezia.host"
STORE_PATH = "/index.php?rp=/store/openstack-vps-and-cloud"
LOGIN_PATH = "/index.php?rp=/login"
CLIENTAREA_PATH = "/clientarea.php"
SERVICES_PATH = "/clientarea.php?action=services"

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class AmneziaError(Exception):
    """Base exception for Amnezia client errors."""


class AmneziaAuthError(AmneziaError):
    """Raised when authentication against my.amnezia.host fails."""


def load_env(path: pathlib.Path | str | None = None) -> bool:
    """Load key-value pairs from a .env file into os.environ.

    Searches explicit path, current working directory, showcase directory,
    and repository root. Returns True if a .env file was found and loaded.
    """
    candidates: list[pathlib.Path] = []
    if path:
        candidates.append(pathlib.Path(path))
    else:
        showcase_dir = pathlib.Path(__file__).resolve().parent
        repo_root = showcase_dir.parents[1]
        candidates.extend(
            [
                pathlib.Path.cwd() / ".env",
                showcase_dir / ".env",
                repo_root / ".env",
            ]
        )

    for candidate in candidates:
        if candidate.is_file():
            try:
                for line in candidate.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if key and key not in os.environ:
                        os.environ[key] = val
                return True
            except OSError as err:
                logger.warning("Could not read %s: %s", candidate, err)
    return False


@dataclass(frozen=True)
class VpsPlan:
    product_id: int
    name: str
    price_monthly_usd: Decimal
    specs: str
    vcpus: int
    ram_gb: int
    disk_gb: int


@dataclass
class AccountInfo:
    email: str
    name: str | None
    credit_balance: str
    active_services: int


class AmneziaClient:
    """Session-aware HTTP client interacting with my.amnezia.host."""

    def __init__(self, user_agent: str = DEFAULT_USER_AGENT):
        self.cookie_jar = http.cookiejar.CookieJar()
        self.ssl_context = ssl.create_default_context()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar),
            urllib.request.HTTPSHandler(context=self.ssl_context),
        )
        self.user_agent = user_agent
        self.logged_in_email: str | None = None

    def _request(
        self,
        path: str,
        data: dict[str, str] | None = None,
        method: str | None = None,
        timeout: int = 20,
    ) -> tuple[int, str, str]:
        """Send an HTTP request and return (status_code, final_url, html_body)."""
        url = f"{BASE_URL}{path}" if path.startswith("/") else path
        encoded_data = None
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if data is not None:
            encoded_data = urllib.parse.urlencode(data).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        req = urllib.request.Request(
            url,
            data=encoded_data,
            headers=headers,
            method=method,
        )
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                status = resp.status
                final_url = resp.geturl()
                body = resp.read().decode("utf-8", errors="replace")
                return status, final_url, body
        except urllib.error.HTTPError as err:
            err_body = ""
            try:
                err_body = err.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            raise AmneziaError(f"HTTP {err.code} from {url}: {err.reason}") from err
        except Exception as err:
            raise AmneziaError(f"Failed to connect to {url}: {err}") from err

    def list_hardware(self) -> list[VpsPlan]:
        """Fetch and parse available VPS plans and pricing from the store."""
        _, _, html = self._request(STORE_PATH)

        pattern = re.compile(
            r'<h3[^>]*>([^<]+)</h3>\s*'
            r'<div class="vps-card__price" id="product(\d+)-price">\s*'
            r'<span class="vps-card__amount">\$?([0-9.]+)</span>\s*'
            r'<span class="vps-card__cycle">([^<]+)</span>[\s\S]*?'
            r'<div class="vps-card__specs">([^<]+)</div>',
            re.MULTILINE,
        )

        plans: list[VpsPlan] = []
        for match in pattern.finditer(html):
            name, pid_str, price_str, _, specs = match.groups()
            specs_clean = specs.strip()

            # Parse vCPU, RAM, Disk from specs string (e.g. "1 vCPU · 2 GB RAM · 20 GB SSD")
            vcpu_m = re.search(r"(\d+)\s*vCPU", specs_clean, re.IGNORECASE)
            ram_m = re.search(r"(\d+)\s*GB\s*RAM", specs_clean, re.IGNORECASE)
            disk_m = re.search(r"(\d+)\s*GB\s*SSD", specs_clean, re.IGNORECASE)

            vcpus = int(vcpu_m.group(1)) if vcpu_m else 1
            ram_gb = int(ram_m.group(1)) if ram_m else 1
            disk_gb = int(disk_m.group(1)) if disk_m else 10

            plans.append(
                VpsPlan(
                    product_id=int(pid_str),
                    name=name.strip(),
                    price_monthly_usd=Decimal(price_str),
                    specs=specs_clean,
                    vcpus=vcpus,
                    ram_gb=ram_gb,
                    disk_gb=disk_gb,
                )
            )

        if not plans:
            raise AmneziaError("Could not extract any VPS plans from the store page.")
        return sorted(plans, key=lambda p: p.price_monthly_usd)

    def _extract_csrf_token(self, html: str) -> str:
        """Extract WHMCS CSRF token from HTML form."""
        m = re.search(r'name=["\']token["\']\s+value=["\']([^"\']+)["\']', html)
        if not m:
            m = re.search(r'value=["\']([^"\']+)["\']\s+name=["\']token["\']', html)
        if not m:
            raise AmneziaError("CSRF token not found on the login page.")
        return m.group(1)

    def login(self, username: str, password: str) -> AccountInfo:
        """Log into my.amnezia.host and return account information."""
        # 1. Fetch login form to obtain fresh CSRF token and session cookies
        _, _, login_html = self._request(LOGIN_PATH)
        token = self._extract_csrf_token(login_html)

        # 2. Submit credentials
        post_data = {
            "token": token,
            "username": username.strip(),
            "password": password,
            "rememberme": "on",
        }
        _, final_url, resp_html = self._request(LOGIN_PATH, data=post_data, method="POST")

        # 3. Detect login errors
        if "rp=/login" in final_url or "Login Details Incorrect" in resp_html:
            err_m = re.search(
                r'<div[^>]*class=["\'][^"\']*alert[ -]danger[^"\']*["\'][^>]*>([\s\S]*?)</div>',
                resp_html,
            )
            detail = re.sub(r"<[^>]+>", "", err_m.group(1)).strip() if err_m else "Invalid username or password"
            raise AmneziaAuthError(f"Login failed: {detail}")

        self.logged_in_email = username.strip()
        logger.info("Successfully logged in as %s", self.logged_in_email)

        # 4. Parse account info from clientarea
        return self.get_account_info(resp_html)

    def get_account_info(self, html: str | None = None) -> AccountInfo:
        """Extract user account summary (credit balance, active services)."""
        if html is None or "clientarea" not in html:
            _, _, html = self._request(CLIENTAREA_PATH)

        # Extract credit balance from the dashboard tile
        balance_m = re.search(
            r'<div[^>]*class=["\']stat["\'][^>]*>(\$[0-9,.]+(?:\s*USD)?)</div>\s*<div[^>]*class=["\']title["\']>Current Balance</div>',
            html,
            re.IGNORECASE,
        )
        if not balance_m:
            balance_m = re.search(r"(\$[0-9,.]+\s*USD|[0-9,.]+\s*USD|\$[0-9,.]+)", html)
        balance = balance_m.group(1).strip() if balance_m else "$0.00 USD"

        # Extract services count from the dashboard Services tile
        services_m = re.search(
            r'<div[^>]*class=["\']stat["\'][^>]*>(\d+)</div>\s*<div[^>]*class=["\']title["\']>Services</div>',
            html,
            re.IGNORECASE,
        )
        active_services = int(services_m.group(1)) if services_m else 0

        # Extract name if available
        name_m = re.search(r'<div[^>]*class=["\'][^"\']*user-info["\'][^>]*>[\s\S]*?<strong>([^<]+)</strong>', html)
        user_name = name_m.group(1).strip() if name_m else None

        return AccountInfo(
            email=self.logged_in_email or "unknown",
            name=user_name,
            credit_balance=balance,
            active_services=active_services,
        )

    def list_services(self) -> list[dict[str, str]]:
        """List active or pending VPS services on the account."""
        _, _, html = self._request(SERVICES_PATH)
        services: list[dict[str, str]] = []

        # Find table rows representing services
        rows = re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", html)
        for row in rows:
            if "productdetails" not in row:
                continue
            id_m = re.search(r"id=(\d+)", row)
            name_m = re.search(r"<strong>([^<]+)</strong>", row)
            status_m = re.search(r'<span[^>]*class=["\'][^"\']*status-([a-z]+)["\'][^>]*>([^<]+)</span>', row, re.IGNORECASE)

            services.append(
                {
                    "service_id": id_m.group(1) if id_m else "",
                    "name": name_m.group(1).strip() if name_m else "",
                    "status": status_m.group(2).strip() if status_m else "Unknown",
                }
            )
        return services
