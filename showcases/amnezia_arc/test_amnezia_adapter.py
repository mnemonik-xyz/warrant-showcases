"""Unit tests for AmneziaClient adapter and CLI using mocked HTTP responses."""

from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from showcases.amnezia_arc.amnezia_adapter import (  # noqa: E402
    AccountInfo,
    AmneziaAuthError,
    AmneziaClient,
    AmneziaError,
    VpsPlan,
    deploy,
    load_env,
)
from showcases.amnezia_arc.cli import main as cli_main  # noqa: E402

SAMPLE_STORE_HTML = """
<html>
<body>
<h3>Start</h3>
<div class="vps-card__price" id="product15-price">
    <span class="vps-card__amount">$5.50</span>
    <span class="vps-card__cycle">/ mo</span>
</div>
<div class="vps-card__specs">1 vCPU · 1 GB RAM · 20 GB SSD</div>

<h3>Basic</h3>
<div class="vps-card__price" id="product16-price">
    <span class="vps-card__amount">$6.45</span>
    <span class="vps-card__cycle">/ mo</span>
</div>
<div class="vps-card__specs">1 vCPU · 2 GB RAM · 20 GB SSD</div>
</body>
</html>
"""

SAMPLE_STORE_VARIATIONS_HTML = """
<html>
<body>
<h3>Power NVMe</h3>
<div id="product20-price" class="vps-card__price">
    <span class="vps-card__amount">$1,031.95</span>
    <span class="vps-card__cycle">/ mo</span>
</div>
<div class="vps-card__specs">8 Cores · 8 GB Memory · 160 GB NVMe</div>
</body>
</html>
"""

SAMPLE_LOGIN_FORM_HTML = """
<html>
<body>
<form action="/index.php?rp=/login" method="post">
    <input type="hidden" name="token" value="abc123csrf" />
    <input type="email" name="username" />
    <input type="password" name="password" />
</form>
</body>
</html>
"""

SAMPLE_CLIENTAREA_HTML = """
<html>
<body>
<div class="user-info"><strong>Jane Doe</strong></div>
<a href="clientarea.php?action=addfunds" class="tile">
    <div class="stat">$10.00 USD</div>
    <div class="title">Current Balance</div>
</a>
<a href="clientarea.php?action=services" class="tile">
    <div class="stat">1</div>
    <div class="title">Services</div>
</a>
</body>
</html>
"""

SAMPLE_SERVICES_HTML = """
<html>
<body>
<table class="table">
    <tr>
        <th>Product/Service</th>
        <th>Pricing</th>
        <th>Status</th>
    </tr>
    <tr>
        <td><strong>Basic VPS (EU-AMS)</strong><br><a href="clientarea.php?action=productdetails&id=101">Manage</a></td>
        <td>$6.45 USD</td>
        <td><span class="status-active">Active</span></td>
    </tr>
    <tr>
        <td><strong>Start VPS</strong><br><a href="clientarea.php?action=productdetails&id=102">Manage</a></td>
        <td>$5.50 USD</td>
        <td><span class="status-pending">Pending</span></td>
    </tr>
</table>
</body>
</html>
"""

SAMPLE_LOGIN_FAIL_HTML = """
<html>
<body>
<div class="alert alert-danger">Login Details Incorrect. Please try again.</div>
</body>
</html>
"""

SAMPLE_CHECKOUT_HTML = """
<html>
<body>
<form id="frmCheckout" method="post" action="/cart.php?a=checkout">
    <input type="hidden" name="token" value="tok_checkout_123" />
    <strong id="totalCartPrice">$5.50 USD</strong>
</form>
</body>
</html>
"""

SAMPLE_ORDER_COMPLETE_HTML = """
<html>
<body>
<div class="order-complete">Your Order Number is: <b>54321</b></div>
</body>
</html>
"""


class AmneziaClientTests(unittest.TestCase):
    def setUp(self):
        self.client = AmneziaClient()

    @patch.object(AmneziaClient, "_request")
    def test_list_hardware(self, mock_request):
        mock_request.return_value = (200, "https://my.amnezia.host/store", SAMPLE_STORE_HTML)
        plans = self.client.list_hardware()

        self.assertEqual(len(plans), 2)
        self.assertEqual(plans[0].product_id, 15)
        self.assertEqual(plans[0].name, "Start")
        self.assertEqual(plans[0].price_monthly_usd, Decimal("5.50"))
        self.assertEqual(plans[0].vcpus, 1)
        self.assertEqual(plans[0].ram_gb, 1)
        self.assertEqual(plans[0].disk_gb, 20)

        self.assertEqual(plans[1].product_id, 16)
        self.assertEqual(plans[1].name, "Basic")
        self.assertEqual(plans[1].price_monthly_usd, Decimal("6.45"))
        self.assertEqual(plans[1].ram_gb, 2)

    @patch.object(AmneziaClient, "_request")
    def test_list_hardware_variations(self, mock_request):
        mock_request.return_value = (200, "https://my.amnezia.host/store", SAMPLE_STORE_VARIATIONS_HTML)
        plans = self.client.list_hardware()

        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].product_id, 20)
        self.assertEqual(plans[0].name, "Power NVMe")
        self.assertEqual(plans[0].price_monthly_usd, Decimal("1031.95"))
        self.assertEqual(plans[0].vcpus, 8)
        self.assertEqual(plans[0].ram_gb, 8)
        self.assertEqual(plans[0].disk_gb, 160)

    @patch.object(AmneziaClient, "_request")
    def test_list_hardware_empty_raises(self, mock_request):
        mock_request.return_value = (200, "https://my.amnezia.host/store", "<html><body>No products</body></html>")
        with self.assertRaises(AmneziaError) as ctx:
            self.client.list_hardware()
        self.assertIn("Could not extract any VPS plans", str(ctx.exception))

    @patch.object(AmneziaClient, "_request")
    def test_login_success(self, mock_request):
        mock_request.side_effect = [
            (200, "https://my.amnezia.host/index.php?rp=/login", SAMPLE_LOGIN_FORM_HTML),
            (200, "https://my.amnezia.host/clientarea.php", SAMPLE_CLIENTAREA_HTML),
        ]

        account = self.client.login("jane@example.com", "secret123")
        self.assertEqual(account.email, "jane@example.com")
        self.assertEqual(account.name, "Jane Doe")
        self.assertIn("$10.00 USD", account.credit_balance)
        self.assertEqual(account.active_services, 1)

    @patch.object(AmneziaClient, "_request")
    def test_login_failure(self, mock_request):
        mock_request.side_effect = [
            (200, "https://my.amnezia.host/index.php?rp=/login", SAMPLE_LOGIN_FORM_HTML),
            (200, "https://my.amnezia.host/index.php?rp=/login", SAMPLE_LOGIN_FAIL_HTML),
        ]

        with self.assertRaises(AmneziaAuthError) as ctx:
            self.client.login("bad@example.com", "wrong")
        self.assertIn("Login Details Incorrect", str(ctx.exception))

    def test_csrf_token_formats(self):
        token_html_meta = '<meta name="csrf-token" content="token_meta_123" />'
        token_html_rev = '<input type="hidden" value="token_rev_456" name="token" />'
        token_html_attr = '<input type="hidden" name="token" class="form-control" value="token_attr_789" />'

        self.assertEqual(self.client._extract_csrf_token(token_html_meta), "token_meta_123")
        self.assertEqual(self.client._extract_csrf_token(token_html_rev), "token_rev_456")
        self.assertEqual(self.client._extract_csrf_token(token_html_attr), "token_attr_789")

        with self.assertRaises(AmneziaError):
            self.client._extract_csrf_token("<html><body>No token</body></html>")

    @patch.object(AmneziaClient, "_request")
    def test_list_services(self, mock_request):
        mock_request.return_value = (
            200,
            "https://my.amnezia.host/clientarea.php?action=services",
            SAMPLE_SERVICES_HTML,
        )
        services = self.client.list_services()

        self.assertEqual(len(services), 2)
        self.assertEqual(services[0]["service_id"], "101")
        self.assertEqual(services[0]["name"], "Basic VPS (EU-AMS)")
        self.assertEqual(services[0]["status"], "Active")

        self.assertEqual(services[1]["service_id"], "102")
        self.assertEqual(services[1]["name"], "Start VPS")
        self.assertEqual(services[1]["status"], "Pending")

    @patch.object(AmneziaClient, "_request")
    def test_deploy_dry_run(self, mock_request):
        mock_request.side_effect = [
            (200, "https://my.amnezia.host/cart.php?a=view", "<html>Empty</html>"),
            (200, "https://my.amnezia.host/store/general-eu-ams-1", "<html>Config</html>"),
            (200, "https://my.amnezia.host/cart.php", ""),
            (200, "https://my.amnezia.host/cart.php?a=checkout&e=false", SAMPLE_CHECKOUT_HTML),
            (200, "https://my.amnezia.host/cart.php?a=view", "<html>Empty</html>"),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            res = deploy(self.client, 15, state_path=state_file, dry_run=True)
            self.assertEqual(res["phase"], "dry_run")
            self.assertEqual(res["total_price"], "$5.50 USD")
            self.assertTrue(state_file.exists())

    @patch.object(AmneziaClient, "_request")
    def test_deploy_payment_required(self, mock_request):
        mock_request.side_effect = [
            (200, "https://my.amnezia.host/cart.php?a=view", "<html>Empty</html>"),
            (200, "https://my.amnezia.host/store/general-eu-ams-1", "<html>Config</html>"),
            (200, "https://my.amnezia.host/cart.php", ""),
            (200, "https://my.amnezia.host/cart.php?a=checkout&e=false", SAMPLE_CHECKOUT_HTML),
            (200, "https://my.amnezia.host/viewinvoice.php?id=888", "<html>Invoice #888</html>"),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            res = deploy(self.client, 15, state_path=state_file, dry_run=False)
            self.assertEqual(res["phase"], "payment_required")
            self.assertEqual(res["invoice_id"], "888")
            self.assertIn("viewinvoice.php?id=888", res["payment_url"])

    @patch.object(AmneziaClient, "_request")
    def test_deploy_order_completed(self, mock_request):
        mock_request.side_effect = [
            (200, "https://my.amnezia.host/cart.php?a=view", "<html>Empty</html>"),
            (200, "https://my.amnezia.host/store/general-eu-ams-1", "<html>Config</html>"),
            (200, "https://my.amnezia.host/cart.php", ""),
            (200, "https://my.amnezia.host/cart.php?a=checkout&e=false", SAMPLE_CHECKOUT_HTML),
            (200, "https://my.amnezia.host/cart.php?a=complete", SAMPLE_ORDER_COMPLETE_HTML),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            res = deploy(self.client, 15, state_path=state_file, dry_run=False)
            self.assertEqual(res["phase"], "deployed")
            self.assertEqual(res["order_id"], "54321")

    @patch.object(AmneziaClient, "list_hardware")
    def test_deploy_budget_exceeded(self, mock_list_hw):
        mock_list_hw.return_value = [
            VpsPlan(15, "Start", Decimal("5.50"), "1 vCPU", 1, 1, 20),
        ]
        with self.assertRaises(AmneziaError) as ctx:
            deploy(self.client, 15, max_cost_usd="2.00")
        self.assertIn("exceeds max_cost_usd budget limit", str(ctx.exception))

    def test_load_env_from_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text(
                "# Test comment\n"
                "AMNEZIA_TEST_KEY_1=sample_val\n"
                "AMNEZIA_TEST_KEY_2='quoted_val'\n"
                'AMNEZIA_TEST_KEY_3="double_quoted"\n'
                "export AMNEZIA_TEST_KEY_4=exported_val\n"
            )

            loaded = load_env(env_file)
            self.assertTrue(loaded)
            self.assertEqual(os.environ.get("AMNEZIA_TEST_KEY_1"), "sample_val")
            self.assertEqual(os.environ.get("AMNEZIA_TEST_KEY_2"), "quoted_val")
            self.assertEqual(os.environ.get("AMNEZIA_TEST_KEY_3"), "double_quoted")
            self.assertEqual(os.environ.get("AMNEZIA_TEST_KEY_4"), "exported_val")


class AmneziaCliTests(unittest.TestCase):
    @patch.object(AmneziaClient, "list_hardware")
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_cli_main_skip_login(self, mock_stdout, mock_list_hardware):
        mock_list_hardware.return_value = [
            VpsPlan(
                product_id=15,
                name="Start",
                price_monthly_usd=Decimal("5.50"),
                specs="1 vCPU · 1 GB RAM · 20 GB SSD",
                vcpus=1,
                ram_gb=1,
                disk_gb=20,
            )
        ]

        exit_code = cli_main(["--skip-login"])
        self.assertEqual(exit_code, 0)
        output = mock_stdout.getvalue()
        self.assertIn("Found 1 VPS tiers", output)
        self.assertIn("Start", output)
        self.assertIn("--skip-login specified", output)

    @patch.object(AmneziaClient, "list_hardware")
    @patch("showcases.amnezia_arc.cli.load_env", return_value=False)
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_cli_main_missing_credentials(self, mock_stdout, mock_load_env, mock_list_hardware):
        mock_list_hardware.return_value = []
        with patch.dict(os.environ, {}, clear=True):
            exit_code = cli_main([])
        self.assertEqual(exit_code, 0)
        output = mock_stdout.getvalue()
        self.assertIn("AMNEZIA_EMAIL / AMNEZIA_PASSWORD not set", output)

    @patch.object(AmneziaClient, "list_services")
    @patch.object(AmneziaClient, "login")
    @patch.object(AmneziaClient, "list_hardware")
    @patch("sys.stdout", new_callable=io.StringIO)
    def test_cli_main_authenticated(self, mock_stdout, mock_list_hw, mock_login, mock_list_services):
        mock_list_hw.return_value = []
        mock_login.return_value = AccountInfo(
            email="test@example.com",
            name="Test User",
            credit_balance="$50.00 USD",
            active_services=1,
        )
        mock_list_services.return_value = [{"service_id": "99", "name": "Test VPS", "status": "Active"}]

        exit_code = cli_main(["--email", "test@example.com", "--password", "secret"])
        self.assertEqual(exit_code, 0)
        output = mock_stdout.getvalue()
        self.assertIn("SUCCESS: Authenticated successfully!", output)
        self.assertIn("Test User", output)
        self.assertIn("$50.00 USD", output)
        self.assertIn("Test VPS", output)


if __name__ == "__main__":
    unittest.main()
