#!/usr/bin/env python3
"""Forward GitHub notifications to a Slack DM, filtered by configurable rules.

Reads your GitHub notification inbox, matches each item against the rules in
config.json, and DMs you a color-coded Slack card for the ones that match.
State is tracked in state.json so you never get a duplicate ping.

What to notify on, the colors, and which repos all live in config.json.
Secrets come from the environment (never config.json):
  GH_PAT, SLACK_BOT_TOKEN, SLACK_USER_ID
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

CONFIG_FILE = os.environ.get("CONFIG_FILE", "config.json")
STATE_FILE = os.environ.get("STATE_FILE", "state.json")

TICKET_RE = re.compile(r"\bAIR-\d+\b")
LINEAR_ISSUE_URL = "https://linear.app/airops/issue/"

# Human-readable verb per GitHub notification "reason", used when a rule
# does not set its own label.
REASON_VERB = {
    "review_requested": "Review requested",
    "mention": "You were mentioned",
    "team_mention": "Team mention",
    "comment": "New comment",
    "state_change": "Merged / closed",
    "assign": "Assigned",
    "author": "Activity on your PR",
    "subscribed": "Activity on your PR",
    "ci_activity": "CI activity",
}


# --------------------------------------------------------------------------- config
@dataclass
class Rule:
    color: str                          # Slack color bar (hex or good/warning/danger)
    name: str = ""                      # category name, shown in test mode
    reasons: list | None = None         # match these GitHub reasons; None = any
    authored_by_me: bool | None = None  # require (or exclude) PRs you authored
    label: str | None = None            # override the displayed verb (else from reason)


@dataclass
class Config:
    github_login: str
    lookback_hours: int
    repos: list                         # allowlist of "owner/name"; empty = all repos
    rules: list


def load_config(path):
    raw = json.load(open(path))
    return Config(
        github_login=raw["github_login"].lower(),
        lookback_hours=raw.get("lookback_hours", 24),
        repos=[r.lower() for r in raw.get("repos", [])],
        rules=[Rule(**r) for r in raw["rules"]],
    )


# --------------------------------------------------------------------------- github
def gh(url):
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {os.environ['GH_PAT']}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "pr-slack-notifier",
    })
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def list_notifications(lookback_hours):
    since = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out, page = [], 1
    while page <= 10:
        batch = gh(f"https://api.github.com/notifications?all=true&since={since}&per_page=50&page={page}")
        if not batch:
            break
        out.extend(batch)
        if len(batch) < 50:
            break
        page += 1
    return out


def pr_author(url, cache):
    if url not in cache:
        try:
            cache[url] = gh(url).get("user", {}).get("login", "").lower()
        except urllib.error.HTTPError as e:
            print(f"WARN: could not read {url} (HTTP {e.code}) -- token may lack repo / SSO access", file=sys.stderr)
            cache[url] = ""
    return cache[url]


def api_to_html(url):
    return url.replace("https://api.github.com/repos/", "https://github.com/").replace("/pulls/", "/pull/")


# --------------------------------------------------------------------------- slack
_dm_channel = None


def _slack(method, payload):
    req = urllib.request.Request(
        f"https://slack.com/api/{method}",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {os.environ['SLACK_BOT_TOKEN']}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def dm_channel():
    global _dm_channel
    if _dm_channel is None:
        resp = _slack("conversations.open", {"users": os.environ["SLACK_USER_ID"]})
        if not resp.get("ok"):
            raise RuntimeError(f"conversations.open failed: {resp.get('error')}")
        _dm_channel = resp["channel"]["id"]
    return _dm_channel


def slack_card(verb, repo, title, url, color):
    body = f"*{verb}*"
    ticket = TICKET_RE.search(title or "")
    if ticket:
        body += f"\n<{LINEAR_ISSUE_URL}{ticket.group(0)}|{ticket.group(0)}>"
    resp = _slack("chat.postMessage", {
        "channel": dm_channel(),
        "unfurl_links": False,
        "unfurl_media": False,
        "attachments": [{
            "color": color,
            "author_name": repo,
            "title": title or repo,
            "title_link": url,
            "text": body,
            "mrkdwn_in": ["text"],
        }],
    })
    if not resp.get("ok"):
        print("chat.postMessage error:", resp.get("error"), file=sys.stderr)


# --------------------------------------------------------------------------- matching
def match(notif, cfg, author_cache):
    """Return the first Rule that matches this notification, or None."""
    reason = notif.get("reason", "")
    subject = notif.get("subject", {})
    is_pr = subject.get("type") == "PullRequest"
    for rule in cfg.rules:
        if rule.reasons is not None and reason not in rule.reasons:
            continue
        if rule.authored_by_me is not None:
            mine = bool(is_pr and subject.get("url")
                        and pr_author(subject["url"], author_cache) == cfg.github_login)
            if mine != rule.authored_by_me:
                continue
        return rule
    return None


def verb_for(rule, reason):
    return rule.label or REASON_VERB.get(reason, reason.replace("_", " ").title())


# --------------------------------------------------------------------------- main
def run_test(cfg):
    for rule in cfg.rules:
        label = rule.label or rule.name or "Example"
        slack_card(label, "owner/repo", f"[AIR-0000] Example: {rule.name or label}",
                   "https://github.com", rule.color)
    print(f"sent {len(cfg.rules)} test cards")


def main():
    cfg = load_config(CONFIG_FILE)

    if os.environ.get("TEST_DM") == "1":
        run_test(cfg)
        return

    state = json.load(open(STATE_FILE)) if os.path.exists(STATE_FILE) else {}
    first_run = not state
    author_cache = {}
    sent = 0

    notifications = list_notifications(cfg.lookback_hours)
    for n in notifications:
        nid, updated = n["id"], n["updated_at"]
        if state.get(nid) == updated:
            continue
        state[nid] = updated
        if first_run:
            continue  # seed only on the first run; don't backfill a flood

        repo = n.get("repository", {}).get("full_name", "")
        if cfg.repos and repo.lower() not in cfg.repos:
            continue

        rule = match(n, cfg, author_cache)
        if rule is None:
            continue

        subject = n.get("subject", {})
        url = api_to_html(subject["url"]) if subject.get("url") else n.get("repository", {}).get("html_url", "")
        latest = subject.get("latest_comment_url")
        if latest:
            try:
                url = gh(latest).get("html_url", url)
            except urllib.error.HTTPError:
                pass

        slack_card(verb_for(rule, n.get("reason", "")), repo, subject.get("title", ""), url, rule.color)
        sent += 1

    if len(state) > 2000:
        state = dict(sorted(state.items(), key=lambda kv: kv[1], reverse=True)[:1000])
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=0, sort_keys=True)

    print(f"{'seeded' if first_run else f'sent {sent}'} (scanned {len(notifications)} notifications)")


if __name__ == "__main__":
    main()
