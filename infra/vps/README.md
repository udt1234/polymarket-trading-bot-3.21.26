# Dublin VPS runbook (execution host)

Why: no Railway region can place CLOB orders and the CF worker no longer
bypasses the order geoblock (verified 2026-07-06, BUILD_SPEC Part M).
Ireland is geo-allowed and ~2ms from the matching engine.

## 1. AWS account (Sir, ~10 min, one time)
1. Sign up: https://aws.amazon.com/free -> "Create a Free Account"
   (root email + card; pick the free tier).
2. Console -> region selector (top right) -> **Europe (Ireland) eu-west-1**.

## 2. Launch the instance (Sir or vAI-via-Chrome once logged in)
1. EC2 -> Launch instance.
2. Name `polybot-dublin`; AMI **Ubuntu Server 24.04 LTS (64-bit x86)**.
3. Type **t3.small** (or t3.micro if riding the free tier).
4. Key pair: "Proceed without a key pair" (cloud-init installs ours).
5. Network: allow SSH (TCP 22) from "My IP" only. Nothing else inbound.
6. Storage: 20 GB gp3.
7. Advanced details -> User data -> paste `infra/vps/cloud-init.yaml`.
8. Launch. Grab the public IP.

## 3. First contact (vAI, from this machine)
```
ssh -i ~/.ssh/polybot_dublin polybot@<PUBLIC_IP>
```

## 4. Secrets (never in the repo)
Create `/home/polybot/bot/.env` on the box (copy values from
`~/.credentials/shared.env`): POLYMARKET_* block, SUPABASE_URL,
SUPABASE_SERVICE_KEY, TWITTERAPI_IO_KEY, TELEGRAM_*, BANKROLL.
Then `chmod 600 .env` and `sudo systemctl enable --now polybot`.
NOTE: do NOT set POLYMARKET_PROXY_URL here - Dublin talks to Polymarket
directly; the worker is only for geo-awkward read-only hosts.

## 5. Acceptance (vAI)
```
cd ~/bot && ~/venv/bin/python -u scripts/step2_acceptance.py   # BOT wallet (once funded)
curl -s localhost:8000/api/healthz
```
Step 2 passes when the post-only order RESTS then cancels, confirmed via
the user WS. Then Step 5 latency measurement, then the Step 7 micro-size
round trip.

## Security notes
- Private key material only in `.env` (600, owner polybot). Consider AWS
  SSM Parameter Store later (Part N key-security item).
- SSH is key-only (cloud-init installs no passwords); UFW default-deny.
- Clock: chrony + UTC (V2 ms-timestamp signing horizon).
