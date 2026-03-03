# Technology Stack

**Project:** AI Voice Caller (Matt) - SignalWire Agents SDK
**Researched:** 2026-02-17
**Context:** Brownfield rebuild for existing macpro-hosted outbound calling system

---

## Executive Summary

This stack combines **SignalWire Agents SDK (Python)** with **GCP serverless** infrastructure and **persistent tunneling** for a hybrid deployment pattern. The calling mechanism runs on a local server (macpro) with ngrok tunnel, while SWAIG webhooks remain on Google Cloud Functions. This is the ONLY architecture that works for SignalWire AI outbound calls in 2026.

**Confidence:** HIGH (all components verified via official docs)

---

## Core Framework

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| **SignalWire Agents SDK** | Latest (pip) | AI agent runtime + SWML generation | ONLY path that supports AI outbound calls. Compatibility API requires cXML (XML), Calling API needs Realtime SDK client-side. Agents SDK is the only server-side solution. |
| **Python** | 3.12 | Runtime language | SDK requires 3.8+. 3.12 is current stable (already installed on macpro). GCF supports 3.7-3.14, so 3.12 maintains compatibility across local + cloud. |
| **Uvicorn** | Latest | ASGI server | SignalWire Agents SDK uses ASGI. Uvicorn is the official recommended server (built on uvloop + httptools for speed). |
| **Gunicorn** | Latest (with uvicorn workers) | Process manager | Production-grade process supervision with multi-worker support. Use `gunicorn -k uvicorn.workers.UvicornWorker` for ASGI apps. |

**Rationale:**
- SignalWire has 3 APIs: Compatibility (cXML only), Calling (client SDK only), Agents SDK (server + AI). Agents SDK is non-negotiable.
- ASGI (not WSGI) because SignalWire SDK is async-native
- Uvicorn alone lacks process management; Gunicorn provides worker supervision, graceful restarts, zero-downtime deploys

---

## Infrastructure

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| **ngrok** | Latest (v3+) | Persistent tunnel | Free tier supports persistent subdomains. Alternatives (frp, rathole, Cloudflare Tunnel) require more setup. ngrok is battle-tested and just works. |
| **systemd** | Native (Ubuntu) | Service orchestration | Built into Ubuntu. Manages both ngrok tunnel + SignalWire agent server. More lightweight than Supervisor, native to system. |
| **macpro** | Ubuntu 24.04 | Local server | Existing infrastructure. SignalWire needs a persistent tunnel endpoint — cloud functions timeout, lambdas are session-based. Local server + tunnel is the only stable pattern. |

**Rationale:**
- **Why not serverless for calling?** SignalWire Agents SDK requires a persistent HTTP endpoint for the agent runtime. Cloud Functions timeout after 60s (GCP) or 15min (AWS Lambda). Calls can last 5-10 minutes. Session-based functions don't work.
- **Why not Supervisor?** systemd is already installed, lighter, and handles both ngrok + app as separate units. Supervisor adds Python dependency for minimal gain.
- **Why not self-hosted tunnel (frp/rathole)?** Additional server + config overhead. ngrok free tier provides persistent subdomain + auto-SSL, which is all we need.

---

## Database & Cloud Services

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| **Google Cloud Firestore** | google-cloud-firestore 2.23.0+ | Primary datastore | Already in use. NoSQL fits call logs + contact data patterns. Real-time listeners for callbacks. Free tier covers SLED volume (35 targets). |
| **Google Cloud Functions** | Python 3.12 runtime | SWAIG webhooks | Already deployed (6 functions). SWAIG functions are stateless + event-driven — perfect for GCF. SignalWire POSTs to these during calls. |
| **Google Cloud Secret Manager** | google-cloud-secret-manager | Credentials vault | For Salesforce + Gmail credentials (not in .env files). Standard GCP pattern. |

**Rationale:**
- Firestore already has data (contacts, call_logs, lead_scores). Migration cost > staying.
- SWAIG webhooks (save_contact, log_call, etc.) are stateless — ideal for serverless.
- Secret Manager prevents credential leaks in code/logs.

---

## Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| **signalwire-agents** | Latest | Base SDK | Always. Install without extras: `pip install signalwire-agents` |
| **signalwire-agents[search]** | N/A | Vector search skills | Only if adding knowledge-base search to agent prompts. NOT needed for basic calling. |
| **google-cloud-firestore** | 2.23.0+ | Firestore client | All scripts that read/write call data, contacts, leads |
| **google-cloud-secret-manager** | Latest | Secret retrieval | For loading SF/Gmail credentials in production |
| **requests** | Latest | HTTP client (sync) | For SignalWire Fabric API calls (create/delete agents). Sync is fine for admin ops. |
| **httpx** | Latest | Async HTTP client | If adding async external API calls in SWAIG functions. NOT needed if GCF handles all webhooks. |
| **structlog** | Latest | Structured logging | Production logging. JSON output for GCP Cloud Logging compatibility. |
| **python-dotenv** | Latest | Environment config | Local dev .env loading. Production uses systemd EnvironmentFile. |

**Rationale:**
- Don't install `signalwire-agents[search-all]` (~700MB) unless adding vector search — bloats Docker images.
- `requests` is fine for Fabric API (admin ops, not hot path). Only use `httpx` if agent runtime needs async HTTP.
- `structlog` > `logging` for production — GCP Cloud Logging ingests JSON natively, makes querying/alerting easier.

---

## Process Management Pattern

### systemd Services (recommended for macpro)

**Service 1: ngrok tunnel**
```ini
[Unit]
Description=ngrok tunnel for SignalWire agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=samson
WorkingDirectory=/home/samson
ExecStart=/usr/local/bin/ngrok start --all --config /home/samson/.config/ngrok/ngrok.yml
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

**Service 2: SignalWire agent server**
```ini
[Unit]
Description=SignalWire AI Agent - Matt
After=network-online.target ngrok.service
Requires=ngrok.service

[Service]
Type=notify
User=samson
WorkingDirectory=/home/samson/.openclaw/workspace/projects/ai-voice-caller
EnvironmentFile=/home/samson/.openclaw/workspace/projects/ai-voice-caller/.env
ExecStart=/home/samson/.openclaw/workspace/projects/ai-voice-caller/.venv/bin/gunicorn \
  -k uvicorn.workers.UvicornWorker \
  --workers 2 \
  --bind 0.0.0.0:3000 \
  --timeout 120 \
  --graceful-timeout 30 \
  server:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**Why this pattern:**
- ngrok starts first, establishes tunnel
- Agent server `Requires=ngrok.service` ensures dependency
- `Type=notify` for Gunicorn (sends ready signal)
- `--workers 2` is enough for SLED volume (35 targets, 1-2 concurrent calls max)
- `--timeout 120` handles 2-minute calls before worker restart

---

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| **Calling mechanism** | Agents SDK (local server) | Compatibility API | Compatibility API only supports cXML (XML), silently ignores SWML JSON. TESTED: connects silent calls with no AI. |
| **Calling mechanism** | Agents SDK (local server) | Calling API + Realtime SDK | Realtime SDK is client-side (browser/mobile). Server can't use it. Would need to build browser automation, massive complexity. |
| **Tunnel** | ngrok | Cloudflare Tunnel | Cloudflare Tunnel requires domain + Cloudflare account. ngrok free tier gives persistent subdomain instantly. |
| **Tunnel** | ngrok | frp / rathole (self-hosted) | Requires second server to host relay, config overhead. ngrok is simpler for SLED scale. |
| **Process manager** | systemd | Supervisor | Supervisor adds Python dependency, extra config. systemd is native + lighter. |
| **Process manager** | systemd + Gunicorn | PM2 | PM2 is for Node.js. Python ecosystem uses Gunicorn or systemd directly. |
| **ASGI server** | Uvicorn | Hypercorn | Uvicorn is more mature, SignalWire docs reference it. Hypercorn is newer, less tested. |
| **Database** | Firestore | PostgreSQL | Firestore already has data. SLED volume (35 targets) fits free tier. Postgres adds hosting cost. |
| **Logging** | structlog (JSON) | stdlib logging (text) | GCP Cloud Logging parses JSON natively. Text logs need custom parsing. |

---

## Installation

### Local Server (macpro)

```bash
# System dependencies
sudo apt update
sudo apt install -y python3.12 python3.12-venv nginx

# Install ngrok (if not present)
curl -s https://ngrok-agent.s3.amazonaws.com/ngrok.asc | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null
echo "deb https://ngrok-agent.s3.amazonaws.com buster main" | sudo tee /etc/apt/sources.list.d/ngrok.list
sudo apt update
sudo apt install ngrok

# Configure ngrok (persistent subdomain)
ngrok config add-authtoken <YOUR_TOKEN>
# Edit ~/.config/ngrok/ngrok.yml:
# version: "2"
# authtoken: <token>
# tunnels:
#   matt-agent:
#     proto: http
#     addr: 3000
#     subdomain: matt-agent-sled  # requires paid plan OR use random subdomain

# Create virtual environment
cd ~/.openclaw/workspace/projects/ai-voice-caller
python3.12 -m venv .venv
source .venv/bin/activate

# Install Python dependencies
pip install --upgrade pip
pip install signalwire-agents
pip install google-cloud-firestore google-cloud-secret-manager
pip install requests python-dotenv structlog
pip install gunicorn uvicorn[standard]

# Create .env file
cat > .env <<EOF
SIGNALWIRE_SPACE=6eyes.signalwire.com
SIGNALWIRE_PROJECT_ID=<project_id>
SIGNALWIRE_TOKEN=<auth_token>
GOOGLE_APPLICATION_CREDENTIALS=/home/samson/.gcp/tatt-pro-service-account.json
GCP_PROJECT_ID=tatt-pro
EOF

# Set up systemd services
sudo cp systemd/ngrok.service /etc/systemd/system/
sudo cp systemd/matt-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable ngrok matt-agent
sudo systemctl start ngrok matt-agent

# Verify
sudo systemctl status ngrok
sudo systemctl status matt-agent
curl http://localhost:3000/health  # should return agent status
```

### Google Cloud Functions (SWAIG webhooks)

```bash
# Already deployed — no changes needed
# Functions: swaigWebhook (handles 6 SWAIG functions)
# Endpoint: https://us-central1-tatt-pro.cloudfunctions.net/swaigWebhook

# To redeploy (if needed):
cd cloud-functions/swaig
gcloud functions deploy swaigWebhook \
  --runtime python312 \
  --trigger-http \
  --allow-unauthenticated \
  --region us-central1 \
  --project tatt-pro \
  --set-env-vars GCP_PROJECT_ID=tatt-pro
```

---

## Configuration Best Practices

### 1. Environment Variables (systemd EnvironmentFile)

```bash
# .env (NOT committed to git)
SIGNALWIRE_SPACE=6eyes.signalwire.com
SIGNALWIRE_PROJECT_ID=<project_id>
SIGNALWIRE_TOKEN=<auth_token>
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
GCP_PROJECT_ID=tatt-pro
LOG_LEVEL=INFO
```

Reference in systemd: `EnvironmentFile=/path/to/.env`

### 2. Logging Configuration (structlog)

```python
import structlog

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

log = structlog.get_logger()
log.info("call_started", call_id="abc123", to="+16025551234")
# Output: {"event": "call_started", "call_id": "abc123", "to": "+16025551234", "timestamp": "2026-02-17T10:30:00Z", "level": "info"}
```

### 3. Firestore Connection Pattern

```python
from google.cloud import firestore

# Uses GOOGLE_APPLICATION_CREDENTIALS env var
db = firestore.Client(project="tatt-pro")

# Write with timestamp
db.collection("call_logs").add({
    "call_id": call_id,
    "to": phone,
    "status": "completed",
    "timestamp": firestore.SERVER_TIMESTAMP
})

# Follow 500/50/5 rule for new collections
# Start at 500 ops/sec, increase 50% every 5 min
```

### 4. ngrok Persistent Tunnel Configuration

```yaml
# ~/.config/ngrok/ngrok.yml
version: "2"
authtoken: <YOUR_NGROK_TOKEN>
tunnels:
  matt-agent:
    proto: http
    addr: 3000
    # Free tier: random subdomain each restart (e.g., abc123.ngrok-free.app)
    # Paid tier ($10/mo): subdomain: matt-agent-sled
```

**Gotcha:** Free tier subdomains rotate on restart. For production, either:
- Use paid ngrok ($10/mo for persistent subdomain)
- OR use Cloudflare Tunnel (free, requires domain)
- OR self-host frp (free, requires relay server)

For SLED MVP (35 targets), recommend **paid ngrok** — $10/mo is cheaper than maintaining frp relay server.

---

## Deployment Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ SignalWire Platform (6eyes.signalwire.com)                  │
│ ┌────────────────┐         ┌────────────────┐              │
│ │ Phone Number   │         │ Fabric API     │              │
│ │ +14806024668   │         │ (create agents)│              │
│ └────────────────┘         └────────────────┘              │
│         │                           │                        │
│         │ (receives call)           │ (admin ops)           │
│         ▼                           ▼                        │
│ ┌──────────────────────────────────────────────┐            │
│ │ AI Agent Runtime (SWML execution)            │            │
│ │ - Connects to agent server via tunnel        │            │
│ │ - Streams audio bidirectionally              │            │
│ │ - Calls SWAIG webhooks during conversation   │            │
│ └──────────────────────────────────────────────┘            │
└─────────────────────────────────────────────────────────────┘
         │ (tunnel)                      │ (SWAIG POST)
         ▼                               ▼
┌─────────────────────────┐    ┌──────────────────────────────┐
│ ngrok Tunnel            │    │ Google Cloud Functions       │
│ matt-agent.ngrok.io     │    │ us-central1-tatt-pro         │
│ (HTTPS → localhost:3000)│    │                              │
└─────────────────────────┘    │ ┌──────────────────────────┐ │
         │                     │ │ swaigWebhook             │ │
         ▼                     │ │ - save_contact           │ │
┌─────────────────────────┐    │ │ - log_call               │ │
│ macpro (192.168.0.39)   │    │ │ - score_lead             │ │
│                         │    │ │ - save_lead              │ │
│ ┌─────────────────────┐ │    │ │ - schedule_callback      │ │
│ │ systemd             │ │    │ │ - send_info_email        │ │
│ │ ├─ ngrok.service    │ │    │ └──────────────────────────┘ │
│ │ └─ matt-agent.svc   │ │    └──────────────────────────────┘
│ └─────────────────────┘ │               │ (Firestore writes)
│ ┌─────────────────────┐ │               ▼
│ │ Gunicorn            │ │    ┌──────────────────────────────┐
│ │ ├─ Uvicorn worker 1 │ │    │ Google Cloud Firestore       │
│ │ └─ Uvicorn worker 2 │ │    │ (tatt-pro)                   │
│ └─────────────────────┘ │    │                              │
│ ┌─────────────────────┐ │    │ Collections:                 │
│ │ SignalWire Agent    │ │    │ - contacts                   │
│ │ (Python SDK runtime)│ │    │ - call_logs                  │
│ │ - SWML generation   │ │    │ - lead_scores                │
│ │ - Agent definition  │ │    │ - cold-call-leads            │
│ │ - SWAIG routing     │ │    │ - callbacks                  │
│ └─────────────────────┘ │    │ - email-queue                │
└─────────────────────────┘    └──────────────────────────────┘
```

**Flow:**
1. Campaign script (on macpro) calls SignalWire Calling API with inline SWML
2. SignalWire connects call, executes SWML `ai` verb
3. SWML points to agent server: `https://matt-agent.ngrok.io/agent`
4. ngrok tunnels request to localhost:3000 → Gunicorn → Uvicorn → SignalWire SDK
5. SDK generates agent definition with SWAIG function URLs (GCF endpoints)
6. During call, SignalWire POSTs to SWAIG webhooks (GCF) as needed
7. SWAIG functions write to Firestore (contacts, call_logs, etc.)

---

## Version Requirements Summary

| Component | Minimum | Recommended | Notes |
|-----------|---------|-------------|-------|
| Python | 3.8 | 3.12 | SDK requires 3.8+, GCF supports 3.7-3.14 |
| signalwire-agents | N/A | Latest from PyPI | No version pinning recommended (SDK is actively developed) |
| google-cloud-firestore | 2.20.0 | 2.23.0+ | Matches existing macpro install |
| gunicorn | 20.0+ | Latest | Use with `-k uvicorn.workers.UvicornWorker` |
| uvicorn | 0.20.0+ | Latest | Install with `[standard]` extras for full features |
| ngrok | 3.0+ | Latest | v3+ has improved tunnel stability |
| Ubuntu | 20.04 | 24.04 | systemd 245+, Python 3.12 in repos |

---

## Critical Gotchas & What NOT to Use

### ❌ DO NOT Use SignalWire Compatibility API for AI Calls

```python
# WRONG — connects silent calls, SWML ignored
requests.post(
    f"https://{space}/api/laml/2010-04-01/Accounts/{project_id}/Calls.json",
    data={
        "From": "+14806024668",
        "To": "+16025551234",
        "Url": "https://example.com/swml.json"  # ❌ Expects XML, ignores SWML
    }
)
```

**Why:** Compatibility API is LaML/cXML (XML) only. `Url` parameter expects XML response. SWML JSON is silently ignored → bare call with no instructions → silence.

### ❌ DO NOT Use SignalWire Calling API Without Inline SWML

```python
# WRONG — needs Realtime SDK client-side, not for server use
requests.post(
    f"https://{space}/api/calling/calls",
    json={
        "command": "dial",
        "params": {"from": "+14806024668", "to": "+16025551234"}
        # Missing: "swml" parameter with inline SWML JSON string
    }
)
```

**Why:** Calling API without `swml` parameter requires Realtime SDK (client-side). Server-side calls need inline SWML OR use Agents SDK (which handles SWML generation).

### ❌ DO NOT Point Voice URL to Agent Endpoints

```python
# WRONG — these are not valid call instruction URLs
"Url": "https://6eyes.signalwire.com/api/ai/agent/{agent_id}"  # ❌ Dashboard route
"Url": "https://6eyes.signalwire.com/api/fabric/resources/{resource_id}/execute"  # ❌ 404
```

**Why:** Fabric API resources are read-only by ID. `/execute` endpoint doesn't exist. `/api/ai/agent/{id}` is for dashboard/Fabric routing, not API calls.

### ✅ CORRECT Pattern: Agents SDK on Local Server

```python
# agents_server.py
from signalwire.agent import AgentBase

agent = AgentBase("Matt", route="/agent")

@agent.tool
def save_contact(name: str, phone: str, email: str):
    """Save contact to Firestore"""
    # ... Firestore write

agent.serve(host="0.0.0.0", port=3000)

# Call placement script
import requests
import json

swml = {
    "version": "1.0.0",
    "sections": {
        "main": [
            {"answer": {}},
            {"ai": {"agent": "https://matt-agent.ngrok.io/agent"}}
        ]
    }
}

response = requests.post(
    f"https://{space}/api/calling/calls",
    auth=(project_id, auth_token),
    json={
        "command": "dial",
        "params": {
            "from": "+14806024668",
            "to": "+16025551234",
            "caller_id": "+14806024668",
            "swml": json.dumps(swml)  # ✅ Inline SWML as JSON string
        }
    }
)
```

---

## Testing & Validation Checklist

Before deployment, verify:

- [ ] Python 3.12 installed: `python3.12 --version`
- [ ] Virtual environment created: `.venv/bin/python --version`
- [ ] SignalWire SDK installed: `pip list | grep signalwire-agents`
- [ ] Firestore connection works: `python -c "from google.cloud import firestore; firestore.Client(project='tatt-pro')"`
- [ ] ngrok tunnel active: `curl https://matt-agent.ngrok.io/health`
- [ ] systemd services enabled: `systemctl is-enabled ngrok matt-agent`
- [ ] systemd services running: `systemctl is-active ngrok matt-agent`
- [ ] Logs structured (JSON): `journalctl -u matt-agent -n 10 | grep '"event"'`
- [ ] SWAIG webhooks reachable: `curl -X POST https://us-central1-tatt-pro.cloudfunctions.net/swaigWebhook -d '{"function":"save_contact"}'`

---

## Sources

### SignalWire Agents SDK
- [SignalWire Agents SDK Docs](https://developer.signalwire.com/sdks/agents-sdk/)
- [GitHub: signalwire/signalwire-agents](https://github.com/signalwire/signalwire-agents)
- [PyPI: signalwire-agents](https://pypi.org/project/signalwire-agents/)
- [Core Features Blog](https://signalwire.com/blogs/developers/agents-sdk-python-core-features)
- [Cloud Functions Guide](https://developer.signalwire.com/sdks/agents-sdk/guides/cloud-functions/)
- [SWAIG Functions Docs](https://developer.signalwire.com/sdks/agents-sdk/swaig-functions/)

### Python Stack (2026)
- [FastAPI async best practices](https://fastapi.tiangolo.com/async/)
- [FastAPI vs Flask 2026](https://docs.kanaries.net/articles/fastapi-vs-flask)
- [Uvicorn production deployment](https://oneuptime.com/blog/post/2026-02-03-python-uvicorn-production/view)
- [Gunicorn + Uvicorn guide](https://leapcell.io/blog/deploying-python-web-apps-for-production-with-gunicorn-uvicorn-and-nginx)

### Infrastructure
- [ngrok systemd units](https://github.com/ngrok/ngrok-systemd)
- [Supervisor vs systemd](https://medium.com/@annxsa/managing-php-worker-processes-on-linux-supervisor-vs-systemd-5781e07263ed)
- [ngrok alternatives 2026](https://github.com/anderspitman/awesome-tunneling)

### Google Cloud Platform
- [GCP Python version support](https://cloud.google.com/run/docs/runtimes/python)
- [Firestore best practices](https://firebase.google.com/docs/firestore/best-practices)
- [Firestore Python SDK](https://cloud.google.com/python/docs/reference/firestore/latest)

### Logging
- [Python logging best practices 2026](https://betterstack.com/community/guides/logging/python/python-logging-best-practices/)
- [Structured logging guide](https://signoz.io/guides/python-logging-best-practices/)
