# ClawdBot v3.0 🦞

An extremely capable AI assistant for Mac control. Smart routing saves money while delivering quality.

## Features

- **Smart 3-Tier Routing**: Free → GLM (cheap) → Claude (quality)
- **Telegram Integration**: Control your Mac remotely from anywhere
- **Task Planning**: Complex multi-step operations with verification
- **Persistent Memory**: Learns your preferences and intents
- **Real-time Dashboard**: Monitor all systems and agents
- **Wallpaper System**: 4K wallpapers via WallHaven + macOS integration

## Architecture

```
User Input
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│                    SMART ROUTER                         │
└─────────────────────────────────────────────────────────┘
    │                    │                    │
    ▼                    ▼                    ▼
┌─────────┐        ┌─────────┐        ┌─────────────────┐
│ DIRECT  │        │   GLM   │        │     CLAUDE      │
│  FREE   │        │  CHEAP  │        │     SMART       │
└─────────┘        └─────────┘        └─────────────────┘
    │                    │                    │
    ▼                    ▼                    ▼
• Wallpaper          • Simple Q&A        • Task Planning
• Open apps          • Chat              • Code Generation
• Bash cmds          • Greetings         • Complex tasks
• File read                              • Multi-step ops
```

## Agents

| Agent | Model | Purpose | Cost |
|-------|-------|---------|------|
| GLM Agent | glm-4-flash | Simple chat | $0.10/1M tokens |
| Claude Agent | claude-sonnet-4 | Complex tasks | $3-15/1M tokens |
| Bash Agent | native | Shell commands | Free |
| File Agent | native | Read/write files | Free |
| Web Agent | DuckDuckGo | Web search | Free |
| Wallpaper Agent | WallHaven | Find wallpapers | Free |

## Setup

```bash
# Clone
git clone https://github.com/YOUR_USERNAME/clawdbot-v2.git
cd clawdbot-v2

# Create venv
python3 -m venv venv
source venv/bin/activate

# Install deps
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your API keys
```

## Usage

### CLI Mode
```bash
source venv/bin/activate
python clawdbot.py
```

### Telegram Bot
```bash
source venv/bin/activate
python clawdbot.py --telegram
```

### Dashboard
```bash
source venv/bin/activate
streamlit run dashboard.py
```

## Commands

**Direct (Free):**
- `wallpaper <anything>` - Set 4K wallpaper
- `open <app/url>` - Open apps or websites
- `run <command>` - Execute bash commands
- `read <file>` - Read file contents

**Smart (AI):**
- Any question - GLM handles simple, Claude handles complex
- `create a script...` - Plans and executes multi-step tasks
- `fix this code...` - Analyzes and modifies code

**Telegram:**
- `/start` - Initialize bot
- `/help` - Show commands
- `/costs` - Show spending
- `/screenshot` - Take screenshot

## Environment Variables

```bash
CLAUDE_API_KEY=sk-ant-...
GLM_API_KEY=...
TELEGRAM_TOKEN=...
```

## License

MIT
