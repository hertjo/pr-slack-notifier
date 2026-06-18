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

## Configuration (`config.json`)

All behavior lives in `config.json` — no code changes needed.

```json
{
  "github_login": "hertjo",
  "lookback_hours": 24,
  "repos": [],
  "username": "GitHub PR Notifier",
  "icon_emoji": ":bufo-offers-a-pr:",
  "rules": [
    { "name": "Review requested", "reasons": ["review_requested"], "color": "#ECB22E", "icon_emoji": ":bufo-offers-a-pr:" },
    { "name": "Mentions", "reasons": ["mention", "team_mention"], "color": "#E8702A", "icon_emoji": ":bufo-shows-mention-on-pr:" },
    { "name": "Comments on your PRs", "authored_by_me": true, "is_comment": true, "color": "#36C5F0", "icon_emoji": ":bufo-shows-pr-comments:" },
    { "name": "Your PRs", "authored_by_me": true, "color": "#36C5F0", "icon_emoji": ":bufo-shows-pr:" }
  ]
}
```

- **`github_login`** — your GitHub username (used to detect "your" PRs).
- **`lookback_hours`** — how far back to scan each run.
- **`repos`** — allowlist of `"owner/name"`. Empty = all repos. e.g. `["airopshq/airops"]` to only watch one.
- **`username`** / **`icon_emoji`** / **`icon_url`** — the bot's default display name and avatar. `icon_emoji` is a workspace emoji (e.g. `":bufo-offers-a-pr:"`); `icon_url` is a hosted image instead. Any rule can override the emoji per type (below). **Requires the `chat:write.customize` bot scope** (OAuth & Permissions → add scope → reinstall). Until that scope is added, the bot falls back to its default icon and notifications keep working. Emoji names must exist in your workspace.
- **`rules`** — evaluated top to bottom; the **first match wins**. Each rule:
  - `name` — label shown in test mode.
  - `color` — the Slack bar (hex, or `good` / `warning` / `danger`).
  - `icon_emoji` — avatar for this notification type (e.g. a per-type bufo). Omit = use the top-level `icon_emoji`.
  - `reasons` — match these GitHub notification reasons (`review_requested`, `mention`, `team_mention`, `comment`, `state_change`, `ci_activity`, ...). Omit = any reason.
  - `authored_by_me` — `true` = only PRs you authored, `false` = only PRs you did not. Omit = don't care.
  - `is_comment` — `true` = only comment activity (a heuristic on the latest comment), `false` = exclude comments. Omit = don't care. Put a `true` rule above your catch-all so comments get their own emoji.
  - `label` — override the displayed verb. Omit = derived from the reason.

Examples:
- Only your PRs + review requests, nothing else → that's the default above.
- Add a separate red bar for CI failures on your PRs → add `{ "name": "CI", "reasons": ["ci_activity"], "authored_by_me": true, "color": "danger" }` (put it above the "Your PRs" rule so it wins).
- Limit to one repo → set `"repos": ["airopshq/airops"]`.

Edit `config.json`, commit, push — the next run picks it up. Run the workflow with **test_dm** to see one sample card per rule in its color.

## Other knobs
- **Cadence / hours** — in `.github/workflows/notify.yml`: the daytime loop count + `sleep`, and the two `cron` lines (UTC; ~9am-8pm NY at ~2 min, overnight at 15 min).
- Secrets (`GH_PAT`, `SLACK_BOT_TOKEN`, `SLACK_USER_ID`) stay in GitHub Actions secrets, never in `config.json`.
