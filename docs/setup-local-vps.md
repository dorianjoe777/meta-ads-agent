# Local and VPS Setup Guide

This guide is written for customers who want a simple install path.

## Local PC or Mac

### Option A: Docker, recommended for beginners

1. Install Docker Desktop.
2. Open the installer or product folder you received.
3. Open a terminal in the folder.
4. Run:

```bash
./scripts/run-docker.sh
```

5. Open:

```text
http://127.0.0.1:7871
```

Docker installs Python, Node/npm, and Codex CLI inside the container.

### Option B: Direct local install

1. Install Python 3.10 or newer.
2. Open the installer or product folder you received.
3. Open a terminal in the folder.
4. Run:

```bash
./scripts/install-local.sh
./scripts/run-dashboard.sh
```

5. Open:

```text
http://127.0.0.1:7871
```

## VPS

### Docker VPS, recommended

1. Create a small Ubuntu VPS.
2. Install Docker and Docker Compose.
3. Upload the installed product folder.
4. Run:

```bash
./scripts/run-docker.sh
```

5. Visit the server using an SSH tunnel:

```bash
ssh -L 7871:127.0.0.1:7871 user@your-server-ip
```

### Direct VPS install

1. Create a small Ubuntu VPS.
2. Install Python:

```bash
sudo apt update
sudo apt install -y python3 python3-venv
```

3. Upload the installed product folder.
4. Run:

```bash
./scripts/install-local.sh
./scripts/install-systemd-service.sh
```

5. Visit the server using an SSH tunnel:

```bash
ssh -L 7871:127.0.0.1:7871 user@your-server-ip
```

Then open `http://127.0.0.1:7871` on your own computer.

## Safe Default

The product starts as `Con supervision`. That means it reads real Meta data, writes reports, prepares approval items, and does not execute risky changes by surprise.

The installer leaves the dashboard password empty so the buyer creates it during onboarding. It also locks down `.env`, `dashboard/data`, `output`, and `logs`.

Real account changes require:

- Active cloud-validated license.
- working Meta token/account setup
- explicit approval in the dashboard/Telegram, or `Piloto automatico` enabled for allowed changes under the buyer's rules
- Buyer-created dashboard password for protected dashboard actions

For VPS installs, keep the dashboard local and access it with the SSH tunnel above. Do not expose the dashboard port directly to the internet.

## DigitalOcean strict access

If the buyer wants the dashboard reachable from a DigitalOcean server IP without opening it to everyone, use the strict firewall mode:

```bash
./scripts/install-digitalocean-strict-access.sh
```

This mode updates a dedicated DigitalOcean firewall after a successful SSH login. It allows SSH and the dashboard port only from the buyer's current IP. See `docs/es-digitalocean-acceso-estricto.md`.

## Daily Run

Run manually:

```bash
./scripts/run-daily-agent.sh
```

Install a daily morning cron. By default it runs at 7:00am local machine time:

```bash
./scripts/setup-cron.sh
```

To choose another morning time:

```bash
DAILY_AGENT_CRON_HOUR=8 DAILY_AGENT_CRON_MINUTE=30 ./scripts/setup-cron.sh
```

The cron writes `output/daily_brief_YYYY-MM-DD.json`. The dashboard's `Lectura diaria` reads the latest report from that file, so the morning summary reflects the scheduled agent run.

## Troubleshooting

Check configuration and social-cli status:

```bash
python3 src/daily_agent.py status
```

Check logs:

```bash
tail -f logs/daily-agent.log
```

For Docker + Codex CLI details, see `docs/es-instalacion-docker-codex.md`.
