# Deployment

Local-first. Two supported shapes.

## Docker Compose

```bash
cp .env.example .env      # fill in OPENAI_API_KEY, TELEGRAM_BOT_TOKEN, …
docker compose up --build
```

State lives in `./data` (`ARTEMIS_HOME`). Change `command:` in
`docker-compose.yml` to `["bot"]`, `["a2a"]`, `["worker"]` or `["chat"]`.

If you use report charts/PDFs, mount the apollo MCP servers (see the commented
volume in `docker-compose.yml`) and set `CHARTING_DIR` / `PDF_DIR`.

## systemd (Linux, user unit)

```bash
cp deploy/artemis-bot.service ~/.config/systemd/user/
# edit paths in the unit if your checkout is not ~/Workspaces/Artemis
systemctl --user daemon-reload
systemctl --user enable --now artemis-bot
journalctl --user -u artemis-bot -f
```

## launchd (macOS)

```bash
cp deploy/com.artemis.bot.plist ~/Library/LaunchAgents/
# edit the /Users/CHANGE_ME paths
launchctl load ~/Library/LaunchAgents/com.artemis.bot.plist
launchctl start com.artemis.bot
```

## Health

The A2A server exposes `GET /healthz` (database check) for container/service
probes. The Telegram bot and worker are long-running processes; rely on the
service manager's restart policy.

## Backups

```bash
artemis backup ~/artemis-backup.db
artemis export --format json --out transactions.json
```
