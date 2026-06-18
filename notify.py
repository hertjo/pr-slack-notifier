#!/usr/bin/env python3
"""Forward activity on YOUR GitHub PRs (plus @-mentions of you) to a Slack DM.

Reads your GitHub notification feed, keeps only:
  - notifications where you were @-mentioned (any repo), and
  - pull requests you authored (reviews, comments, merges/closes show up here).
Posts the new ones as a Slack DM. State is tracked in state.json so you never get
a duplicate ping for the same event.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

ME = os.environ.get("GITHUB_LOGIN", "hertjo").lower()
GH_PAT = os.environ["GH_PAT"]
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_USER_ID = os.environ["SLACK_USER_ID"]
STATE_FILE = os.environ.get("STATE_FILE", "state.json")
LOOKBACK_HOURS = int(os.environ.get("LOOKBACK_HOURS", "24"))

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


def gh(url):
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {GH_PAT}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "pr-slack-notifier",
    })
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def list_notifications():
    since = (datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
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


def api_to_html(url):
    return (url.replace("https://api.github.com/repos/", "https://github.com/")
               .replace("/pulls/", "/pull/"))


def pr_author(subject_url):
    try:
        return gh(subject_url).get("user", {}).get("login", "").lower()
    except urllib.error.HTTPError as e:
        print(f"WARN: could not read {subject_url} (HTTP {e.code}) -- "
              f"token likely lacks repo access / SSO authorization for that org", file=sys.stderr)
        return ""


def slack_dm(text):
    open_resp = _slack("conversations.open", {"users": SLACK_USER_ID})
    if not open_resp.get("ok"):
        print("conversations.open error:", open_resp.get("error"), file=sys.stderr)
        return
    channel = open_resp["channel"]["id"]
    post_resp = _slack("chat.postMessage", {"channel": channel, "text": text, "unfurl_links": False})
    if not post_resp.get("ok"):
        print("chat.postMessage error:", post_resp.get("error"), file=sys.stderr)


def _slack(method, payload):
    req = urllib.request.Request(
        f"https://slack.com/api/{method}",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def main():
    if os.environ.get("TEST_DM") == "1":
        slack_dm("PR notifier test: Slack delivery works. You'll get a DM here on activity on your PRs or @-mentions.")
        print("sent test DM")
        return

    state = {}
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            state = json.load(f)
    first_run = not state

    notifications = list_notifications()
    author_cache = {}
    sent = 0

    for n in notifications:
        nid, updated = n["id"], n["updated_at"]
        if state.get(nid) == updated:
            continue
        state[nid] = updated
        if first_run:
            continue  # seed state on first run, don't backfill a flood

        subject = n.get("subject", {})
        reason = n.get("reason", "")
        repo = n.get("repository", {}).get("full_name", "")
        subject_url = subject.get("url") or ""
        is_pr = subject.get("type") == "PullRequest"

        mine = False
        if is_pr and subject_url:
            if subject_url not in author_cache:
                author_cache[subject_url] = pr_author(subject_url)
            mine = author_cache[subject_url] == ME

        if not (reason == "mention" or (is_pr and mine)):
            continue

        verb = REASON_VERB.get(reason, reason.replace("_", " ").title())
        title = subject.get("title", "")
        link = api_to_html(subject_url) if subject_url else n.get("repository", {}).get("html_url", "")
        latest = subject.get("latest_comment_url")
        if latest:
            try:
                link = gh(latest).get("html_url", link)
            except urllib.error.HTTPError:
                pass

        slack_dm(f"*{verb}* on <{link}|{repo} — {title}>")
        sent += 1

    if len(state) > 2000:
        state = dict(sorted(state.items(), key=lambda kv: kv[1], reverse=True)[:1000])

    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=0, sort_keys=True)

    print(f"{'seeded' if first_run else f'sent {sent}'} (scanned {len(notifications)} notifications)")


if __name__ == "__main__":
    main()
