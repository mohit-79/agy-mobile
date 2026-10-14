# 🚀 AGY-Mobile 2.0 // Power-User Autonomous Agent Cockpit

A high-performance mobile web interface and control cockpit for **Google Antigravity (AGY)** running on Android via Termux, protected by Cloudflare Edge Gatekeepers and Cloudflare Named Tunnels.

---

## 🏗️ Full-Stack System Architecture

```
                          [ Client Browser ]
                                  │
                                  ▼
                [ Cloudflare Edge Gatekeeper Worker ]
                 (Zero-Trust PIN & Session Cookie)
                                  │
                                  ▼
                     [ Cloudflare Named Tunnel ]
                                  │
          ┌───────────────────────┴───────────────────────┐
          │                                               │
     (HTTP :8080)                                    (WS :8081)
          │                                               │
          ▼                                               ▼
 [ CustomHTTPHandler ]                            [ PTYSession Manager ]
   ├── /api/conversations                           ├── pty.fork()
   ├── /api/flowchart                               └── /usr/bin/agy
   ├── /api/telemetry
   └── /upload & /upload-audio

                                  ▲
                                  │ (Cross-Device File Bridge)
                [ Cloudflare Share Bridge Worker ]
                   (share.yourdomain.com / 24h Buffer)
```

---

## ⚡ Features at a Glance

### 1. Zero-Trust Edge Gateway (`cloudflare/edge-gateway`)
- **Edge Pre-Authentication:** Inbound traffic to `$AGY_DOMAIN` is verified at Cloudflare's global edge network before touching the mobile device.
- **Master PIN Lock:** Edge-computed master PIN validation with 30-day secure HttpOnly session cookies.
- **WebSocket Streaming Proxy:** High-throughput bidirectional PTY frame streaming over WebSockets.

### 2. Universal File Share Bridge (`cloudflare/share-bridge`)
- **Serverless File Bridge:** Instant device-to-device transfers on `$SHARE_DOMAIN`.
- **Dual-Mode:** Drag-and-drop web UI + cURL API for autonomous AGY agents to exchange APKs, keystores, and code archives.

### 3. Sessions Menu Refinements
- **Dual Timestamps:** Human-readable relative time (`2h ago`) alongside exact `YYYY-MM-DD HH:mm` timestamps.
- **Intelligent Categorization Badges:** Automatic intent parsing tags sessions as `[GOAL]`, `[DEBUG]`, `[FEATURE]`, `[PLAN]`, `[RESEARCH]`, or `[CLI]`.

### 4. Command Bar & Input Hub
- **Multi-Select File Attachments:** Select and upload multiple documents simultaneously with dismissible chip badges.
- **Native Audio/Voice Streaming:** Direct HTML5 `MediaRecorder` audio capture streaming voice instructions straight into the agent pipeline.

### 5. Quick Action Bar (Mobile/Touch Enhancements)
- **Virtual Sticky Modifier Engine:** Dedicated **Ctrl**, **Shift**, and **Tab** keys with latching state (`.latched`).
- **Hardware Keyboard Interception:** Combines virtual modifiers with physical keyboards (e.g. tap virtual `Ctrl` + press physical `C` = `\x03`).

### 6. 1-Tap Quick Action Bar 2.0
- `⚡ Goal Mode` (`/goal`)
- `👥 Teamwork Swarm` (`/teamwork-preview`)
- `🔬 Deep Research` (`/boost`)
- `🧪 Code Sandbox` (`/learn`)
- `🧹 Compact` (`/compact`)
- `🛑 Emergency Halt` (`\x03`)

### 7. Live Execution Flowchart (Right Sidebar)
- Real-time interactive node DAG parsing background sub-routines, tool calls, and user intents directly from `transcript.jsonl`.
- Complete transparency into autonomous problem-solving workflows.

### 8. Agent Directory & Telemetry Hub
- Popover modal reporting active PTY sessions, connection health, and real-time agent rosters.

---

## 🔐 Environment & Secret Management

AGY-Mobile isolates all sensitive hostnames, PINs, and session tokens inside `.env`. The `.env` file is excluded from Git via `.gitignore`.

1. Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
2. Configure your confidential parameters:
```env
AGY_DOMAIN=agy.yourdomain.com
AGY_AUTH_PIN=your_master_pin_here
AGY_SESSION_SECRET=your_random_secure_session_secret_here
AGY_HTTP_PORT=8080
AGY_WS_PORT=8081
CF_ZONE_NAME=yourdomain.com
SHARE_DOMAIN=share.yourdomain.com
```

---

## 📂 Repository Layout

```
agy-mobile/
├── .env.example                # Public environment configuration template
├── .gitignore                  # Ignores confidential .env and runtime artifacts
├── cloudflare/
│   ├── edge-gateway/           # Cloudflare Worker zero-trust gatekeeper
│   │   ├── wrangler.toml
│   │   ├── package.json
│   │   └── src/index.js
│   └── share-bridge/           # Cloudflare Worker file bridge
│       ├── wrangler.toml
│       ├── package.json
│       └── src/index.js
├── agy-mobile-app/             # Termux Python Origin Backend & Web Assets
│   ├── server.py               # PTY session daemon & REST endpoints
│   ├── requirements.txt        # Python dependencies (websockets)
│   ├── static/
│   │   └── index.html          # Cockpit 2.0 interface & xterm.js canvas
│   ├── audio/                  # Voice input streaming directory
│   └── uploads/                # Multi-file attachment directory
├── launcher/                   # Android Termux:Widget shortcuts
│   ├── agy-mobile.sh
│   ├── AGY-Mobile.sh
│   └── install-widget.sh
├── tunnel/                     # Cloudflare Named Tunnel configuration
│   └── config.yml.example
├── install.sh                  # 1-Tap Termux installation script
├── agy-mobile.sh               # Root convenience launcher
└── README.md                   # Complete system documentation
```

---

## 📲 Quick Start on Android (Termux)

```bash
# 1. Clone repository
git clone https://github.com/mohit-79/agy-mobile.git
cd agy-mobile

# 2. Configure .env
cp .env.example .env
# Edit .env with your PIN and domain

# 3. Run automated installer
chmod +x install.sh
bash install.sh

# 4. Launch daemon
./agy-mobile.sh
```
