#!/usr/bin/env python3
"""
ClawdBot Dashboard - Real-time monitoring and control
See all agents, systems, logs, memory, and costs in one place
"""

import streamlit as st
import json
import os
import time
import subprocess
from datetime import datetime
from pathlib import Path

# Page config
st.set_page_config(
    page_title="ClawdBot Dashboard",
    page_icon="🦞",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Paths
MEMORY_FILE = os.path.expanduser("~/.clawdbot_memory.json")
LOG_FILE = os.path.expanduser("~/.clawdbot_logs.json")

# Custom CSS
st.markdown("""
<style>
    .stMetric {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        padding: 15px;
        border-radius: 10px;
        border: 1px solid #0f3460;
    }
    .agent-card {
        background: #1a1a2e;
        padding: 15px;
        border-radius: 10px;
        margin: 10px 0;
        border-left: 4px solid #00d4ff;
    }
    .system-active {
        color: #00ff88;
    }
    .system-inactive {
        color: #ff6b6b;
    }
    .log-entry {
        font-family: monospace;
        font-size: 12px;
        padding: 5px;
        border-bottom: 1px solid #333;
    }
</style>
""", unsafe_allow_html=True)


def load_memory():
    """Load ClawdBot memory"""
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {
        "costs": {"total": 0, "session": 0, "glm": 0, "claude": 0},
        "history": [],
        "learned_intents": {},
        "user_preferences": {}
    }


def get_running_processes():
    """Check which ClawdBot processes are running"""
    processes = []
    try:
        result = subprocess.run(
            "ps aux | grep -E 'clawdbot|python.*clawdbot' | grep -v grep",
            shell=True, capture_output=True, text=True
        )
        for line in result.stdout.strip().split('\n'):
            if line:
                parts = line.split()
                if len(parts) > 10:
                    processes.append({
                        'pid': parts[1],
                        'cpu': parts[2],
                        'mem': parts[3],
                        'command': ' '.join(parts[10:])[:60]
                    })
    except:
        pass
    return processes


def get_system_status():
    """Get status of all ClawdBot systems"""
    memory = load_memory()
    processes = get_running_processes()

    # Check which systems are active
    telegram_active = any('--telegram' in p['command'] for p in processes)
    cli_active = any('clawdbot.py' in p['command'] and '--telegram' not in p['command'] for p in processes)

    return {
        'telegram': {
            'name': 'Telegram Bot',
            'status': 'active' if telegram_active else 'inactive',
            'icon': '📱',
            'description': 'Remote control via Telegram'
        },
        'cli': {
            'name': 'CLI Interface',
            'status': 'active' if cli_active else 'inactive',
            'icon': '💻',
            'description': 'Command line interface'
        },
        'memory': {
            'name': 'Persistent Memory',
            'status': 'active' if os.path.exists(MEMORY_FILE) else 'inactive',
            'icon': '🧠',
            'description': f"{len(memory.get('learned_intents', {}))} learned intents"
        },
        'router': {
            'name': 'Smart Router',
            'status': 'active',
            'icon': '🔀',
            'description': 'Routes to GLM (cheap) or Claude (smart)'
        },
        'planner': {
            'name': 'Task Planner',
            'status': 'active',
            'icon': '📋',
            'description': 'Plans multi-step complex tasks'
        },
        'wallpaper': {
            'name': 'Wallpaper System',
            'status': 'active',
            'icon': '🖼️',
            'description': 'WallHaven search + macOS integration'
        }
    }


def get_agents():
    """Define available agents/capabilities"""
    return [
        {
            'name': 'GLM Agent',
            'model': 'glm-4-flash',
            'purpose': 'Simple questions, chat',
            'cost': '$0.10/1M tokens',
            'icon': '💬',
            'color': '#00ff88'
        },
        {
            'name': 'Claude Agent',
            'model': 'claude-sonnet-4',
            'purpose': 'Complex tasks, planning, code',
            'cost': '$3-15/1M tokens',
            'icon': '🧠',
            'color': '#00d4ff'
        },
        {
            'name': 'Bash Agent',
            'model': 'native',
            'purpose': 'Execute shell commands',
            'cost': 'Free',
            'icon': '⚡',
            'color': '#ffcc00'
        },
        {
            'name': 'File Agent',
            'model': 'native',
            'purpose': 'Read/write files, code generation',
            'cost': 'Free (+ Claude for code gen)',
            'icon': '📁',
            'color': '#ff6b6b'
        },
        {
            'name': 'Web Agent',
            'model': 'DuckDuckGo API',
            'purpose': 'Web search and research',
            'cost': 'Free',
            'icon': '🌐',
            'color': '#9b59b6'
        },
        {
            'name': 'Wallpaper Agent',
            'model': 'WallHaven API',
            'purpose': 'Find and set wallpapers',
            'cost': 'Free',
            'icon': '🖼️',
            'color': '#e91e63'
        }
    ]


# Sidebar
with st.sidebar:
    st.title("🦞 ClawdBot")
    st.caption("v3.0 - Extremely Capable")

    st.divider()

    # Quick actions
    st.subheader("Quick Actions")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("▶️ Start Telegram", use_container_width=True):
            subprocess.Popen(
                "source venv/bin/activate && python clawdbot.py --telegram &",
                shell=True, cwd="/Users/shamil/clawdbot-v2"
            )
            st.success("Starting...")
            time.sleep(1)
            st.rerun()

    with col2:
        if st.button("⏹️ Stop All", use_container_width=True):
            subprocess.run("pkill -f 'clawdbot.py'", shell=True)
            st.warning("Stopped")
            time.sleep(1)
            st.rerun()

    if st.button("🔄 Refresh", use_container_width=True):
        st.rerun()

    st.divider()

    # Memory stats
    memory = load_memory()
    st.subheader("💰 Costs")
    st.metric("Total Spent", f"${memory['costs'].get('total', 0):.4f}")
    st.metric("This Session", f"${memory['costs'].get('session', 0):.4f}")

    st.divider()

    # Auto refresh
    auto_refresh = st.checkbox("Auto-refresh (5s)", value=False)
    if auto_refresh:
        time.sleep(5)
        st.rerun()


# Main content
st.title("🦞 ClawdBot Dashboard")
st.caption("Real-time monitoring and control")

# Top metrics
col1, col2, col3, col4 = st.columns(4)

memory = load_memory()
processes = get_running_processes()
systems = get_system_status()

with col1:
    active_systems = sum(1 for s in systems.values() if s['status'] == 'active')
    st.metric("Active Systems", f"{active_systems}/{len(systems)}")

with col2:
    st.metric("Running Processes", len(processes))

with col3:
    st.metric("Learned Intents", len(memory.get('learned_intents', {})))

with col4:
    st.metric("History Items", len(memory.get('history', [])))


# Tabs
tab1, tab2, tab3, tab4, tab5 = st.tabs(["🔧 Systems", "🤖 Agents", "🧠 Memory", "📜 History", "⚙️ Config"])

with tab1:
    st.subheader("System Status")

    cols = st.columns(3)
    for i, (key, system) in enumerate(systems.items()):
        with cols[i % 3]:
            status_color = "🟢" if system['status'] == 'active' else "🔴"
            st.markdown(f"""
            <div class="agent-card">
                <h3>{system['icon']} {system['name']} {status_color}</h3>
                <p>{system['description']}</p>
            </div>
            """, unsafe_allow_html=True)

    st.divider()
    st.subheader("Running Processes")

    if processes:
        for proc in processes:
            st.code(f"PID: {proc['pid']} | CPU: {proc['cpu']}% | MEM: {proc['mem']}% | {proc['command']}")
    else:
        st.info("No ClawdBot processes running")


with tab2:
    st.subheader("Available Agents")

    agents = get_agents()
    cols = st.columns(2)

    for i, agent in enumerate(agents):
        with cols[i % 2]:
            st.markdown(f"""
            <div class="agent-card" style="border-left-color: {agent['color']}">
                <h3>{agent['icon']} {agent['name']}</h3>
                <p><strong>Model:</strong> {agent['model']}</p>
                <p><strong>Purpose:</strong> {agent['purpose']}</p>
                <p><strong>Cost:</strong> {agent['cost']}</p>
            </div>
            """, unsafe_allow_html=True)

    st.divider()
    st.subheader("Agent Flow")
    st.markdown("""
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
    """)


with tab3:
    st.subheader("Persistent Memory")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### 🎯 Learned Intents")
        intents = memory.get('learned_intents', {})
        if intents:
            for phrase, data in intents.items():
                st.markdown(f"- **\"{phrase}\"** → `{data['intent']}`")
                st.caption(f"  Learned: {data.get('learned_at', 'unknown')}")
        else:
            st.info("No learned intents yet")

    with col2:
        st.markdown("### 💾 Raw Memory")
        st.json(memory)

    st.divider()

    if st.button("🗑️ Clear Memory", type="secondary"):
        if os.path.exists(MEMORY_FILE):
            os.remove(MEMORY_FILE)
            st.success("Memory cleared!")
            st.rerun()


with tab4:
    st.subheader("Action History")

    history = memory.get('history', [])
    if history:
        for item in reversed(history[-20:]):
            st.markdown(f"""
            <div class="log-entry">
                <strong>{item.get('time', '')}</strong> |
                {item.get('action', '')} →
                <code>{item.get('result', '')[:100]}</code>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("No history yet")


with tab5:
    st.subheader("Configuration")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### API Keys")
        st.text_input("Claude API Key", value="sk-ant-***", type="password", disabled=True)
        st.text_input("GLM API Key", value="e290e***", type="password", disabled=True)
        st.text_input("Telegram Token", value="8308***", type="password", disabled=True)
        st.caption("Edit .env file to change keys")

    with col2:
        st.markdown("### Paths")
        st.code(f"Memory: {MEMORY_FILE}")
        st.code(f"Project: /Users/shamil/clawdbot-v2")
        st.code(f"Wallpapers: ~/Desktop/wallpaper_*")

    st.divider()

    st.markdown("### Commands")
    st.code("""
# Start CLI
source venv/bin/activate && python clawdbot.py

# Start Telegram bot
source venv/bin/activate && python clawdbot.py --telegram

# Start Dashboard
source venv/bin/activate && streamlit run dashboard.py
    """)


# Footer
st.divider()
st.caption(f"Last updated: {datetime.now().strftime('%H:%M:%S')} | ClawdBot v3.0")
