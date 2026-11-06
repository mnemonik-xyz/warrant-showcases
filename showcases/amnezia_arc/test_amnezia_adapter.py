"""Unit tests for AmneziaClient adapter using mocked HTTP responses."""

from __future__ import annotations

import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch

from showcases.amnezia_arc.amnezia_adapter import (
    AmneziaAuthError,
    AmneziaClient,
    AmneziaError,
    load_env,
)

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

SAMPLE_LOGIN_FAIL_HTML = """
<html>
<body>
<div class="alert alert-danger">Login Details Incorrect. Please try again.</div>
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
    def test_login_success(self, mock_request):
        # Step 1: Login form page returns CSRF token
        # Step 2: POST returns clientarea HTML with 302 redirect
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

    def test_load_env_from_file(self):
        import os
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text(
                "# Test comment\n"
                "AMNEZIA_TEST_KEY_1=sample_val\n"
                "AMNEZIA_TEST_KEY_2='quoted_val'\n"
                "AMNEZIA_TEST_KEY_3=\"double_quoted\"\n"
            )

            loaded = load_env(env_file)
            self.assertTrue(loaded)
            self.assertEqual(os.environ.get("AMNEZIA_TEST_KEY_1"), "sample_val")
            self.assertEqual(os.environ.get("AMNEZIA_TEST_KEY_2"), "quoted_val")
            self.assertEqual(os.environ.get("AMNEZIA_TEST_KEY_3"), "double_quoted")


if __name__ == "__main__":
    unittest.main()
