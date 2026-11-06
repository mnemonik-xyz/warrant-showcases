# Amnezia Hosting Autonomous VPS Showcase with Warrant on Arc

This showcase demonstrates autonomous procurement of VPS infrastructure from Amnezia Hosting
(`my.amnezia.host`) using the Warrant policy framework and escrow settlement on Arc.

---

## 1. Proof-of-Concept: Web Automation & Hardware Discovery

The client adapter ([`amnezia_adapter.py`](amnezia_adapter.py)) simulates API operations against
`my.amnezia.host` using standard web session automation (CSRF handling and cookie persistence)
without requiring heavy external dependencies.

### Run Hardware Discovery (Public Catalog)

To list all current VPS tiers and live pricing in the Netherlands (EU-AMS) without logging in:

```bash
python3 showcases/amnezia_arc/cli.py --skip-login
```

### Run Web Login & Account Check

Create a local `.env` file (which is gitignored) from `.env.example`:

```bash
cp showcases/amnezia_arc/.env.example showcases/amnezia_arc/.env
# Edit showcases/amnezia_arc/.env with your real email & password
```

Then run:

```bash
python3 showcases/amnezia_arc/cli.py
```

`cli.py` automatically detects and loads credentials from `.env` in the current directory, the
showcase folder, or the repository root.

Alternatively, pass credentials via environment variables or flags:

```bash
export AMNEZIA_EMAIL="your_email@example.com"
export AMNEZIA_PASSWORD="your_password"

python3 showcases/amnezia_arc/cli.py
```

Or pass flags directly:

```bash
python3 showcases/amnezia_arc/cli.py --email "user@example.com" --password "secret"
```

---

## 2. Available Hardware Tiers (Netherlands EU-AMS)

| Product ID | Plan | vCPU | RAM | Disk (SSD) | Monthly Price |
|:---:|:---|:---:|:---:|:---:|:---:|
| 15 | **Start** | 1 | 1 GB | 20 GB | $5.50 / mo |
| 16 | **Basic** | 1 | 2 GB | 20 GB | $6.45 / mo |
| 17 | **Advanced** | 2 | 4 GB | 40 GB | $9.95 / mo |
| 18 | **Pro** | 4 | 4 GB | 80 GB | $15.95 / mo |
| 19 | **Pro Plus** | 4 | 8 GB | 80 GB | $19.95 / mo |
| 20 | **Power** | 8 | 8 GB | 160 GB | $31.95 / mo |
| 21 | **Max** | 8 | 16 GB | 160 GB | $39.95 / mo |
| 22 | **Ultra** | 16 | 32 GB | 200 GB | $61.95 / mo |

---

## 3. Deploying a VPS (Dry-Run and Live)

The `deploy` function in [`amnezia_adapter.py`](amnezia_adapter.py) automates the end-to-end
provisioning flow: clearing cart, adding target plan, configuring OS options, and checking out.

### Validate Deployment in Dry-Run Mode

Simulate order creation and verify checkout totals without submitting real payment:

```bash
python3 showcases/amnezia_arc/cli.py --deploy 15 --dry-run
```

With budget limit preflight check and state persistence:

```bash
python3 showcases/amnezia_arc/cli.py --deploy 15 --dry-run --max-cost-usd 6.00 --state state.json
```

---

## 4. Automated Unit Tests

Run the offline unit tests with mocked responses:

```bash
# Run test module directly or via unittest discovery
python3 -m unittest discover showcases/amnezia_arc -v

# Or run the test file directly
python3 showcases/amnezia_arc/test_amnezia_adapter.py
```
