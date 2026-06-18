# PR Slack Notifier

Sends you a Slack DM when something happens on a PR you authored (review, approval, comment, merge/close) or when you're @-mentioned anywhere on GitHub. Runs as a scheduled GitHub Action every 5 minutes, so it works even when your laptop is closed.

It reads your GitHub notification feed, keeps only your-PRs + your-mentions, and DMs you. State lives in `state.json` so you never get a duplicate ping.

## One-time setup

### 1. Push this to a private repo
```sh
cd github-pr-slack-notifier
git init && git add -A && git commit -m "init pr slack notifier"
gh repo create pr-slack-notifier --private --source=. --push
```

### 2. Create the Slack bot
1. https://api.slack.com/apps → **Create New App** → **From scratch** → pick your workspace.
2. **OAuth & Permissions** → **Bot Token Scopes** → add `chat:write` and `im:write`.
3. **Install to Workspace**, then copy the **Bot User OAuth Token** (`xoxb-...`).

### 3. Get your Slack member ID
Slack → your profile → **⋯** → **Copy member ID** (looks like `U0XXXXXXX`).

### 4. Create a GitHub token
GitHub → Settings → Developer settings → **Personal access tokens**.
- Classic: scopes `repo` + `notifications`.
- Or fine-grained: **Notifications: read** + **read** access to `airopshq/airops`.

### 5. Add the repo secrets
In the new repo: Settings → Secrets and variables → Actions → **New repository secret**:
- `GH_PAT` — the token from step 4
- `SLACK_BOT_TOKEN` — the `xoxb-...` token from step 2
- `SLACK_USER_ID` — your member ID from step 3

### 6. Kill the email noise (the whole point)
GitHub → Settings → **Notifications** → turn **off** email, keep the **web/Notification inbox on**. The bot reads that inbox; email stops cluttering your mailbox.

### 7. Seed and go
Actions tab → **PR Slack Notifier** → **Run workflow**. The first run just seeds state silently (no flood). After that it runs every 5 minutes on its own.

## Tweaks
- `GITHUB_LOGIN` (in `.github/workflows/notify.yml`) — set to your GitHub login. Defaults to `hertjo`.
- Cadence — change the `cron` (5 min is GitHub's minimum).
- Want it on *every* PR you're subscribed to, not just yours? Drop the `is_pr and mine` check in `notify.py`.
- `LOOKBACK_HOURS` env — how far back to scan each run (default 24).
