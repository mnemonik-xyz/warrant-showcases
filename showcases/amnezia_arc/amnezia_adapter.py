"""Amnezia Hosting (my.amnezia.host) client adapter.

Provides web session automation for logging in, querying account details and balance,
and listing available VPS hardware tiers.
"""

from __future__ import annotations

import contextlib
import http.cookiejar
import json
import logging
import os
import pathlib
import re
import ssl
import time
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
CART_VIEW_PATH = "/cart.php?a=view"
CART_CHECKOUT_PATH = "/cart.php?a=checkout&e=false"
CART_PATH = "/cart.php"

PRODUCT_SLUGS: dict[int, str] = {
    15: "general-eu-ams-1",
    16: "cloud-vps-1-vcpu-2-gb-ram-20-gb-ssd",
    17: "cloud-vps-2-vcpu-4-gb-ram-40-gb-ssd",
    18: "cloud-vps-4-vcpu-4-gb-ram-80-gb-ssd",
    19: "cloud-vps-4-vcpu-8-gb-ram-80-gb-ssd",
    20: "cloud-vps-8-vcpu-8-gb-ram-160-gb-ssd",
    21: "cloud-vps-8-vcpu-16-gb-ram-160-gb-ssd",
    22: "cloud-vps-16-vcpu-32-gb-ram-200-gb-ssd",
}

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Pre-compiled regex patterns for resilient and efficient HTML extraction
_STORE_PLAN_RE = re.compile(
    r"<h3[^>]*>\s*([^<]+)\s*</h3>\s*"
    r"<div[^>]*id=[\"']product(\d+)-price[\"'][^>]*>\s*"
    r"<span[^>]*class=[\"'][^\"']*vps-card__amount[^\"']*[\"'][^>]*>\s*\$?([0-9.,]+)\s*</span>\s*"
    r"<span[^>]*class=[\"'][^\"']*vps-card__cycle[^\"']*[\"'][^>]*>\s*([^<]+)\s*</span>.*?"
    r"<div[^>]*class=[\"'][^\"']*vps-card__specs[^\"']*[\"'][^>]*>\s*([^<]+)\s*</div>",
    re.DOTALL | re.IGNORECASE,
)
_VCPU_RE = re.compile(r"(\d+)\s*(?:vCPU|CPU|Core)", re.IGNORECASE)
_RAM_RE = re.compile(r"(\d+)\s*GB\s*(?:RAM|Memory)", re.IGNORECASE)
_DISK_RE = re.compile(r"(\d+)\s*GB\s*(?:SSD|NVMe|Storage|Disk|HDD)", re.IGNORECASE)

_CSRF_TOKEN_RE = re.compile(
    r'<input[^>]*name=["\']token["\'][^>]*value=["\']([^"\']+)["\']'
    r'|<input[^>]*value=["\']([^"\']+)["\'][^>]*name=["\']token["\']'
    r'|<meta[^>]*name=["\'](?:csrf-token|token)["\'][^>]*content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)

_LOGIN_ALERT_RE = re.compile(
    r'<div[^>]*class=["\'][^"\']*alert[ -]danger[^"\']*["\'][^>]*>([\s\S]*?)</div>',
    re.IGNORECASE,
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")

_BALANCE_TILE_RE = re.compile(
    r'<div[^>]*class=["\'][^"\']*stat[^"\']*["\'][^>]*>\s*([$€£]?[0-9,.]+(?:\s*[A-Z]{3})?)\s*</div>\s*'
    r'<div[^>]*class=["\'][^"\']*title[^"\']*["\'][^>]*>\s*Current Balance\s*</div>',
    re.IGNORECASE,
)
_BALANCE_REV_RE = re.compile(
    r'<div[^>]*class=["\'][^"\']*title[^"\']*["\'][^>]*>\s*Current Balance\s*</div>\s*'
    r'<div[^>]*class=["\'][^"\']*stat[^"\']*["\'][^>]*>\s*([$€£]?[0-9,.]+(?:\s*[A-Z]{3})?)\s*</div>',
    re.IGNORECASE,
)
_BALANCE_NEARBY_RE = re.compile(
    r"Current\s+Balance[^\d$€£<]{0,50}([$€£]?[0-9,.]+(?:\s*[A-Z]{3})?)",
    re.IGNORECASE,
)

_SERVICES_TILE_RE = re.compile(
    r'<div[^>]*class=["\'][^"\']*stat[^"\']*["\'][^>]*>\s*(\d+)\s*</div>\s*'
    r'<div[^>]*class=["\'][^"\']*title[^"\']*["\'][^>]*>\s*Services\s*</div>',
    re.IGNORECASE,
)
_SERVICES_REV_RE = re.compile(
    r'<div[^>]*class=["\'][^"\']*title[^"\']*["\'][^>]*>\s*Services\s*</div>\s*'
    r'<div[^>]*class=["\'][^"\']*stat[^"\']*["\'][^>]*>\s*(\d+)\s*</div>',
    re.IGNORECASE,
)
_SERVICES_NEARBY_RE = re.compile(
    r"Services[^\d<]{0,30}(\d+)",
    re.IGNORECASE,
)

_USER_NAME_RE = re.compile(
    r'class=["\'][^"\']*(?:user-info|user-profile|account-details)[^"\']*["\'][^>]*>[\s\S]*?<strong>([^<]+)</strong>',
    re.IGNORECASE,
)

_SERVICE_ROW_RE = re.compile(r"<tr[^>]*>([\s\S]*?)</tr>")
_SERVICE_ID_RE = re.compile(r"id=(\d+)")
_SERVICE_NAME_RE = re.compile(r"<strong>([^<]+)</strong>")
_SERVICE_LINK_RE = re.compile(r"<a[^>]*productdetails[^>]*>([\s\S]*?)</a>", re.IGNORECASE)
_SERVICE_STATUS_RE = re.compile(
    r'<span[^>]*class=["\'][^"\']*(?:status|label)[- ]([a-z0-9_-]+)["\'][^>]*>([^<]+)</span>',
    re.IGNORECASE,
)


class AmneziaError(Exception):
    """Base exception for Amnezia client errors."""


class AmneziaAuthError(AmneziaError):
    """Raised when authentication against my.amnezia.host fails."""


def load_env(path: pathlib.Path | str | None = None) -> bool:
    """Load key-value pairs from a .env file into os.environ.

    Searches explicit path, showcase directory, current working directory,
    and repository root. Returns True if at least one .env file was found and loaded.
    """
    candidates: list[pathlib.Path] = []
    if path:
        candidates.append(pathlib.Path(path))
    else:
        showcase_dir = pathlib.Path(__file__).resolve().parent
        repo_root = showcase_dir.parents[1]
        candidates.extend(
            [
                showcase_dir / ".env",
                pathlib.Path.cwd() / ".env",
                repo_root / ".env",
            ]
        )

    seen: set[pathlib.Path] = set()
    unique_candidates: list[pathlib.Path] = []
    for c in candidates:
        try:
            resolved = c.resolve()
        except OSError:
            resolved = c
        if resolved not in seen:
            seen.add(resolved)
            unique_candidates.append(c)

    loaded_any = False
    for candidate in unique_candidates:
        if candidate.is_file():
            try:
                for line in candidate.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("export "):
                        line = line[7:].lstrip()
                    if "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if key and key not in os.environ:
                        os.environ[key] = val
                loaded_any = True
                if path:
                    break
            except OSError as err:
                logger.warning("Could not read %s: %s", candidate, err)
    return loaded_any


@dataclass(frozen=True)
class VpsPlan:
    product_id: int
    name: str
    price_monthly_usd: Decimal
    specs: str
    vcpus: int
    ram_gb: int
    disk_gb: int


@dataclass(frozen=True)
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
            raise AmneziaError(f"HTTP {err.code} from {url}: {err.reason}") from err
        except Exception as err:
            raise AmneziaError(f"Failed to connect to {url}: {err}") from err

    def list_hardware(self) -> list[VpsPlan]:
        """Fetch and parse available VPS plans and pricing from the store."""
        _, _, html = self._request(STORE_PATH)

        plans: list[VpsPlan] = []
        for match in _STORE_PLAN_RE.finditer(html):
            name, pid_str, price_str, _, specs = match.groups()
            specs_clean = specs.strip()

            vcpu_m = _VCPU_RE.search(specs_clean)
            ram_m = _RAM_RE.search(specs_clean)
            disk_m = _DISK_RE.search(specs_clean)

            vcpus = int(vcpu_m.group(1)) if vcpu_m else 1
            ram_gb = int(ram_m.group(1)) if ram_m else 1
            disk_gb = int(disk_m.group(1)) if disk_m else 10

            clean_price = price_str.replace(",", "")
            plans.append(
                VpsPlan(
                    product_id=int(pid_str),
                    name=name.strip(),
                    price_monthly_usd=Decimal(clean_price),
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
        """Extract WHMCS CSRF token from HTML form or meta tag."""
        m = _CSRF_TOKEN_RE.search(html)
        if m:
            token = m.group(1) or m.group(2) or m.group(3)
            if token:
                return token
        raise AmneziaError("CSRF token not found on the login page.")

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
        is_login_page = ("rp=/login" in final_url) or ("/login" in final_url)
        err_m = _LOGIN_ALERT_RE.search(resp_html)
        if is_login_page or "Login Details Incorrect" in resp_html or (err_m and "clientarea" not in final_url):
            detail = _HTML_TAG_RE.sub("", err_m.group(1)).strip() if err_m else "Invalid username or password"
            raise AmneziaAuthError(f"Login failed: {detail}")

        self.logged_in_email = username.strip()
        logger.info("Successfully logged in as %s", self.logged_in_email)

        # 4. Parse account info from clientarea
        return self.get_account_info(resp_html)

    def get_account_info(self, html: str | None = None) -> AccountInfo:
        """Extract user account summary (credit balance, active services)."""
        if html is None or "clientarea" not in html:
            _, _, html = self._request(CLIENTAREA_PATH)

        # Extract credit balance from dashboard tile or contextual label
        balance_m = _BALANCE_TILE_RE.search(html) or _BALANCE_REV_RE.search(html) or _BALANCE_NEARBY_RE.search(html)
        balance = balance_m.group(1).strip() if balance_m else "$0.00 USD"

        # Extract services count from dashboard Services tile
        services_m = _SERVICES_TILE_RE.search(html) or _SERVICES_REV_RE.search(html) or _SERVICES_NEARBY_RE.search(html)
        active_services = int(services_m.group(1)) if services_m else 0

        # Extract name if available
        name_m = _USER_NAME_RE.search(html)
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
        for row_match in _SERVICE_ROW_RE.finditer(html):
            row = row_match.group(1)
            if "productdetails" not in row:
                continue

            id_m = _SERVICE_ID_RE.search(row)
            name_m = _SERVICE_NAME_RE.search(row)
            if not name_m:
                link_m = _SERVICE_LINK_RE.search(row)
                name_str = _HTML_TAG_RE.sub("", link_m.group(1)).strip() if link_m else ""
            else:
                name_str = name_m.group(1).strip()

            status_m = _SERVICE_STATUS_RE.search(row)
            services.append(
                {
                    "service_id": id_m.group(1) if id_m else "",
                    "name": name_str,
                    "status": status_m.group(2).strip() if status_m else "Unknown",
                }
            )
        return services

    def empty_cart(self) -> None:
        """Clear any existing or abandoned items from the shopping cart."""
        _, _, html = self._request(CART_VIEW_PATH)
        m = _CSRF_TOKEN_RE.search(html)
        token = m.group(1) or m.group(2) or m.group(3) if m else None
        if token and ("empty" in html or "Remove" in html or "cart.php?a=checkout" in html):
            self._request(CART_PATH, data={"a": "empty", "token": token}, method="POST")

    def add_to_cart(self, product_id: int) -> None:
        """Add a specific VPS product tier to the cart by its product ID."""
        slug = PRODUCT_SLUGS.get(product_id)
        if not slug:
            raise AmneziaError(f"Unsupported product_id {product_id}. Supported: {sorted(PRODUCT_SLUGS.keys())}")
        store_url = f"{STORE_PATH}/{slug}"
        self._request(store_url)

    def configure_cart_product(
        self,
        billing_cycle: str = "monthly",
        os_option: int = 105,
        disk_option: int = 103,
    ) -> None:
        """Submit product configuration options (OS template, disk size, billing cycle)."""
        data = {
            "ajax": "1",
            "a": "confproduct",
            "configure": "true",
            "i": "0",
            "billingcycle": billing_cycle,
            "configoption[35]": str(os_option),
            "configoption[36]": str(disk_option),
        }
        self._request(CART_PATH, data=data, method="POST")

    def checkout(self, dry_run: bool = False, apply_credit: bool = True) -> dict:
        """Review or complete the order checkout."""
        _, _, html = self._request(CART_CHECKOUT_PATH)

        token = self._extract_csrf_token(html)
        price_m = re.search(r'id=["\']totalCartPrice["\'][^>]*>([^<]+)</strong>', html)
        total_price = price_m.group(1).strip() if price_m else "Unknown"

        if dry_run:
            logger.info("Dry-run checkout validated. Cart total: %s", total_price)
            return {
                "phase": "dry_run",
                "status": "dry_run",
                "total_price": total_price,
                "message": "Checkout validated successfully in dry-run mode. Order was not placed.",
            }

        post_data = {
            "token": token,
            "checkout": "true",
            "custtype": "existing",
            "applycredit": "1" if apply_credit else "0",
            "paymentmethod": "stripecheckout",
        }
        _, final_url, resp_html = self._request("/cart.php?a=checkout", data=post_data, method="POST")

        invoice_m = re.search(r"viewinvoice\.php\?id=(\d+)", final_url) or re.search(r"Invoice #(\d+)", resp_html)
        order_m = re.search(r"Your Order Number is:\s*<b>(\d+)</b>", resp_html, re.IGNORECASE) or re.search(
            r"orderid=(\d+)", final_url
        )

        if invoice_m:
            inv_id = invoice_m.group(1)
            return {
                "phase": "payment_required",
                "status": "payment_required",
                "invoice_id": inv_id,
                "total_price": total_price,
                "payment_url": f"{BASE_URL}/viewinvoice.php?id={inv_id}",
                "message": f"Order placed with invoice #{inv_id}. Payment required.",
            }

        if order_m:
            ord_id = order_m.group(1)
            return {
                "phase": "deployed",
                "status": "deployed",
                "order_id": ord_id,
                "total_price": total_price,
                "message": f"Order #{ord_id} placed and funded via account balance.",
            }

        return {
            "phase": "submitted",
            "status": "submitted",
            "total_price": total_price,
            "final_url": final_url,
            "message": "Order checkout submitted to my.amnezia.host.",
        }


def save_state(path: pathlib.Path | str, state: dict) -> None:
    """Atomically save deployment state to a JSON file."""
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    temp_path = p.with_suffix(".tmp." + str(os.getpid()))
    temp_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(p)


def deploy(
    client: AmneziaClient,
    product: int | dict,
    state_path: pathlib.Path | str | None = None,
    os_option: int = 105,
    disk_option: int = 103,
    billing_cycle: str = "monthly",
    dry_run: bool = False,
    max_cost_usd: Decimal | str | None = None,
) -> dict:
    """Deploy a VPS tier on my.amnezia.host with atomic state tracking.

    Supports either a product ID integer (e.g. 15 for 'Start') or an argument dictionary.
    """
    if isinstance(product, dict):
        product_id = int(product.get("product_id", product.get("hardware_id", 15)))
        os_option = int(product.get("os_option", os_option))
        disk_option = int(product.get("disk_option", disk_option))
        billing_cycle = str(product.get("billing_cycle", billing_cycle))
        dry_run = bool(product.get("dry_run", dry_run))
        max_cost_usd = product.get("max_cost_usd", max_cost_usd)
    else:
        product_id = int(product)

    if product_id not in PRODUCT_SLUGS:
        raise AmneziaError(f"Unsupported product_id {product_id}. Available: {sorted(PRODUCT_SLUGS.keys())}")

    # Budget gate check if specified
    if max_cost_usd is not None:
        limit = Decimal(str(max_cost_usd))
        plans = client.list_hardware()
        matching = [p for p in plans if p.product_id == product_id]
        if matching and matching[0].price_monthly_usd > limit:
            raise AmneziaError(
                f"Selected plan '{matching[0].name}' (${matching[0].price_monthly_usd}) "
                f"exceeds max_cost_usd budget limit (${limit})"
            )

    state = {
        "version": 1,
        "provider": "amnezia.host",
        "created_at": int(time.time()),
        "product_id": product_id,
        "plan_slug": PRODUCT_SLUGS[product_id],
        "phase": "submission_unknown",
        "dry_run": dry_run,
        "max_cost_usd": str(max_cost_usd) if max_cost_usd is not None else None,
    }

    if state_path:
        save_state(state_path, state)

    try:
        # 1. Clean cart
        client.empty_cart()

        # 2. Add product to cart
        client.add_to_cart(product_id)

        # 3. Configure OS, disk, and cycle
        client.configure_cart_product(
            billing_cycle=billing_cycle,
            os_option=os_option,
            disk_option=disk_option,
        )

        # 4. Checkout
        checkout_res = client.checkout(dry_run=dry_run)
        state.update(checkout_res)

        # 5. Clean up cart if dry-run
        if dry_run:
            with contextlib.suppress(Exception):
                client.empty_cart()

    except Exception as exc:
        state["phase"] = "failed"
        state["error"] = str(exc)
        if state_path:
            save_state(state_path, state)
        raise

    if state_path:
        save_state(state_path, state)

    return state
