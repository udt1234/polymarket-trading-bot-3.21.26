"""
Shared library for anchor & spike alert crons.

Provides:
  - send_slack(text, blocks) -- standalone Slack webhook poster
  - load_state / save_state -- dedup state across cron runs
  - polymarket_event_url(slug) -- direct link to auction
"""
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

STATE_DIR = Path(__file__).parent.parent / "_DataMetricPulls" / "alert_state"
STATE_DIR.mkdir(parents=True, exist_ok=True)


def polymarket_event_url(slug: str) -> str:
    return f"https://polymarket.com/event/{slug}"


def send_slack(text: str, blocks: list[dict] | None = None) -> bool:
    """Standalone Slack poster -- reads SLACK_WEBHOOK_URL from env."""
    webhook = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook:
        log.warning("SLACK_WEBHOOK_URL not set; not sending alert")
        return False
    if not webhook.startswith("https://hooks.slack.com/"):
        log.error("SLACK_WEBHOOK_URL is not a hooks.slack.com URL; refusing to post")
        return False
    payload = {"text": text}
    if blocks:
        payload["blocks"] = blocks
    try:
        with httpx.Client(timeout=10) as client:
            res = client.post(webhook, json=payload)
            res.raise_for_status()
            return True
    except Exception as e:
        log.error(f"Slack post failed: {e}")
        return False


def load_state(name: str) -> dict:
    """Load dedup state JSON; returns {} if missing or corrupt."""
    p = STATE_DIR / f"{name}.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def save_state(name: str, state: dict) -> None:
    p = STATE_DIR / f"{name}.json"
    p.write_text(json.dumps(state, indent=2, default=str))


def expire_old_entries(state: dict, key_field: str = "ts", max_age_hours: float = 168) -> dict:
    """Drop entries older than max_age_hours to keep state file from growing forever."""
    now = datetime.now(timezone.utc)
    keep = {}
    for k, v in state.items():
        if not isinstance(v, dict):
            keep[k] = v
            continue
        ts = v.get(key_field)
        if not ts:
            keep[k] = v
            continue
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            age_h = (now - dt).total_seconds() / 3600
            if age_h <= max_age_hours:
                keep[k] = v
        except Exception:
            keep[k] = v
    return keep
