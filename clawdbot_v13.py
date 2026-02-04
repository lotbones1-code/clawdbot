#!/usr/bin/env python3
"""
ClawdBot v13 - Learn by Watching
================================
THE FUNDAMENTAL CHANGE: ClawdBot OBSERVES and LEARNS instead of guessing.

How It Works:
1. DISCOVER - On first run, observes your entire system
2. LEARN - When asked to do something new, learns by asking you step-by-step
3. REMEMBER - Saves workflows as agents for instant replay
4. EXECUTE - Uses learned agents to complete tasks automatically

Key Differences from v12:
- v12: Static knowledge, guessed workflows
- v13: Dynamic learning, observed from YOUR actual system

Commands:
  --discover     Explore your system and save what I find
  --learn TASK   Learn how to do a task interactively
  --agents       List all learned task agents

SETUP: Start Comet with: /Applications/Comet.app/Contents/MacOS/Comet --remote-debugging-port=9222
"""

import os
import re
import json
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from typing import Dict, List, Any, Optional, Callable

import anthropic

# Import components
try:
    from browser_cdp import get_browser_cdp, BrowserCDP
    BROWSER_AVAILABLE = True
except ImportError:
    BROWSER_AVAILABLE = False

try:
    from system_observer import SystemObserver
    OBSERVER_AVAILABLE = True
except ImportError:
    OBSERVER_AVAILABLE = False
    print("⚠ SystemObserver not available")

try:
    from guided_learner import GuidedLearner
    LEARNER_AVAILABLE = True
except ImportError:
    LEARNER_AVAILABLE = False
    print("⚠ GuidedLearner not available")

try:
    from knowledge_manager import KnowledgeManager
    KNOWLEDGE_AVAILABLE = True
except ImportError:
    KNOWLEDGE_AVAILABLE = False

# =============================================================================
# CONFIG
# =============================================================================

CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY") or open(
    os.path.expanduser("~/clawdbot-v2/.env")
).read().split("CLAUDE_API_KEY=")[1].split("\n")[0]

VERSION = "13.0"
MAX_STEPS = 15


# =============================================================================
# TOOL CLASS
# =============================================================================

class Tool:
    def __init__(self, name: str, description: str, execute: Callable):
        self.name = name
        self.description = description
        self._execute = execute

    def execute(self, **params) -> Dict:
        try:
            result = self._execute(**params)
            if isinstance(result, dict):
                return {"success": result.get("success", True), **result}
            return {"success": True, "output": result}
        except Exception as e:
            return {"success": False, "error": str(e)}


# =============================================================================
# LOCAL TOOLS
# =============================================================================

class LocalToolRegistry:
    """Tools for LOCAL macOS tasks"""

    def __init__(self):
        self.tools: Dict[str, Tool] = {}
        self._register_tools()

    def register(self, tool: Tool):
        self.tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self.tools.get(name)

    def list_tools(self) -> str:
        return "\n".join([f"- {n}: {t.description}" for n, t in self.tools.items()])

    def _register_tools(self):
        self.register(Tool("bash", "Run shell command", lambda **kw: self._bash(kw.get("command"))))
        self.register(Tool("open_app", "Open macOS app", lambda **kw: self._open_app(kw.get("app_name"))))
        self.register(Tool("send_imessage", "Send iMessage", lambda **kw: self._send_imessage(kw.get("recipient"), kw.get("message"))))

    def _bash(self, command: str) -> Dict:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
        return {"stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode}

    def _open_app(self, app_name: str) -> Dict:
        subprocess.run(["open", "-a", app_name], capture_output=True)
        return {"opened": app_name}

    def _send_imessage(self, recipient: str, message: str) -> Dict:
        db_path = os.path.expanduser("~/Library/Messages/chat.db")
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM handle WHERE LOWER(id) LIKE ?", (f"%{recipient.lower()}%",))
            matches = cursor.fetchall()
            conn.close()
            if not matches:
                return {"sent": False, "error": f"Contact '{recipient}' not found"}
            actual_recipient = matches[0][0]
        except Exception as e:
            return {"sent": False, "error": str(e)}

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(ROWID) FROM message")
        before_max = cursor.fetchone()[0] or 0
        conn.close()

        message_safe = message.replace('\\', '\\\\').replace('"', '\\"')
        recipient_safe = actual_recipient.replace('\\', '\\\\').replace('"', '\\"')
        script = f'''
        tell application "Messages"
            set targetService to 1st account whose service type = iMessage
            set targetBuddy to participant "{recipient_safe}" of targetService
            send "{message_safe}" to targetBuddy
        end tell
        '''
        subprocess.run(["osascript", "-e", script], capture_output=True, text=True)

        time.sleep(1)
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(ROWID) FROM message")
        after_max = cursor.fetchone()[0] or 0
        conn.close()

        return {"sent": True, "verified": after_max > before_max, "recipient": actual_recipient}


# =============================================================================
# CLAWDBOT v13 - LEARN BY WATCHING
# =============================================================================

class ClawdBot:
    """
    ClawdBot v13 - Learn by Watching

    Instead of guessing, ClawdBot now:
    1. OBSERVES your actual system
    2. LEARNS tasks by asking you step-by-step
    3. REMEMBERS workflows as agents
    4. EXECUTES learned agents automatically
    """

    def __init__(self):
        self.claude = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

        # Browser
        self.browser = get_browser_cdp() if BROWSER_AVAILABLE else None

        # System Observer - see what's on your computer
        self.observer = SystemObserver() if OBSERVER_AVAILABLE else None

        # Guided Learner - learn tasks interactively
        self.learner = GuidedLearner(self.browser) if LEARNER_AVAILABLE else None

        # Legacy knowledge (still useful)
        self.knowledge = KnowledgeManager() if KNOWLEDGE_AVAILABLE else None

        # Local tools
        self.local_tools = LocalToolRegistry()

    def log(self, tag: str, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"{ts} [{tag:8}] {msg}")

    # =========================================================================
    # SYSTEM DISCOVERY
    # =========================================================================

    def discover_system(self):
        """Discover and document the user's system"""
        if not self.observer:
            print("✗ System observer not available")
            return

        self.observer.discover_all(save=True)

    # =========================================================================
    # TASK LEARNING
    # =========================================================================

    def learn_task(self, task_name: str, site: str = None, start_url: str = None):
        """Learn a new task interactively"""
        if not self.learner:
            print("✗ Guided learner not available")
            return

        self.learner.learn_task(task_name, site or "", start_url)

    def list_agents(self):
        """List all learned agents"""
        if not self.learner:
            print("✗ Guided learner not available")
            return

        agents = self.learner.list_agents()
        if not agents:
            print("No learned agents yet.")
            print("Use 'learn <task>' to teach me something!")
            return

        print(f"\n📚 Learned Agents ({len(agents)}):")
        print("=" * 50)
        for name in agents:
            agent = self.learner.load_agent(name)
            if agent:
                task = agent.get("task", "?")
                site = agent.get("site", "?")
                steps = agent.get("total_steps", len(agent.get("steps", [])))
                learned = agent.get("learned_at", "?")[:10]
                print(f"  {name}")
                print(f"    Task: {task} | Site: {site}")
                print(f"    Steps: {steps} | Learned: {learned}")

    # =========================================================================
    # REQUEST ROUTING
    # =========================================================================

    def needs_imessage(self, request: str) -> bool:
        r = request.lower()
        social = ['instagram', 'twitter', 'facebook', 'linkedin', 'discord', 'whatsapp', 'on ig', 'on insta']
        if any(p in r for p in social):
            return False
        if 'imessage' in r or 'text message' in r:
            return True
        if r.startswith('text ') or ' text ' in r:
            return True
        if 'message' in r and (' to ' in r or r.startswith('message ')):
            return True
        return False

    def needs_browser(self, request: str) -> bool:
        kw = ['instagram', 'twitter', 'x.com', 'facebook', 'youtube', 'linkedin',
              'follow', 'like', 'post', 'tweet', 'browse', 'website', 'web',
              'dm', 'message on instagram', 'on ig', 'on insta']
        return any(k in request.lower() for k in kw)

    def extract_task_info(self, request: str) -> Dict:
        """Extract task type, site, recipient, message from request"""
        r = request.lower()

        info = {"task": "unknown", "site": "", "recipient": "", "message": ""}

        # Detect site
        if "instagram" in r or "insta" in r or " ig" in r:
            info["site"] = "instagram.com"
        elif "twitter" in r or "x.com" in r:
            info["site"] = "twitter.com"
        elif "youtube" in r:
            info["site"] = "youtube.com"
        elif "facebook" in r:
            info["site"] = "facebook.com"

        # Detect task
        if any(kw in r for kw in ["dm", "message", "send"]):
            info["task"] = "send_dm"
        elif "follow" in r:
            info["task"] = "follow_user"
        elif "search" in r:
            info["task"] = "search"
        elif "like" in r:
            info["task"] = "like_post"

        # Extract recipient and message for DMs
        if info["task"] == "send_dm":
            # Pattern: "send dm to abeer on instagram saying hello"
            patterns = [
                r'(?:dm|message)\s+(?:to\s+)?(\w+).*?(?:saying|with|:)\s*["\']?(.+?)["\']?$',
                r'(?:send|dm|message)\s+(\w+)\s+(?:on\s+\w+\s+)?(?:saying|with)\s+(.+)',
                r'(?:message|dm)\s+(\w+)\s+(?:on\s+\w+)?\s*(.+)?',
            ]
            for pattern in patterns:
                match = re.search(pattern, request, re.IGNORECASE)
                if match:
                    info["recipient"] = match.group(1)
                    info["message"] = match.group(2) if len(match.groups()) > 1 else ""
                    break

        return info

    # =========================================================================
    # MAIN PROCESSING
    # =========================================================================

    def process(self, request: str) -> str:
        """Process a request - now with learned agents!"""
        text = request.lower().strip()

        if not text:
            return None

        # Built-in commands
        if text in ['quit', 'exit', 'q']:
            return "EXIT"
        if text in ['help', '?']:
            return self.get_help()
        if text == 'discover':
            self.discover_system()
            return "System discovery complete."
        if text.startswith('learn '):
            task = text[6:].strip()
            self.learn_task(task)
            return "Learning complete."
        if text == 'agents':
            self.list_agents()
            return ""
        if text == 'status':
            return self.get_status()

        # iMessage
        if self.needs_imessage(request):
            self.log("MODE", "iMessage")
            return self.handle_imessage(request)

        # Browser task - check for learned agent first!
        if self.needs_browser(request):
            info = self.extract_task_info(request)
            self.log("MODE", f"Browser task: {info['task']} on {info['site']}")

            # Check for learned agent
            if self.learner:
                agent = self.learner.find_agent_for_task(info["task"], info["site"])

                if agent:
                    self.log("AGENT", f"Found learned agent: {agent.get('task')}")
                    params = {
                        "recipient": info.get("recipient", ""),
                        "message": info.get("message", ""),
                    }
                    result = self.learner.execute_agent(agent, params)

                    if result.get("success"):
                        return f"✓ Task complete! Used learned agent.\n  Steps: {result.get('completed_steps')}"
                    else:
                        return f"✗ Agent failed: {result.get('error')}"

                else:
                    # No agent - offer to learn
                    self.log("LEARN", "No agent found for this task")
                    print(f"\n❓ I don't know how to do '{info['task']}' on {info['site']} yet.")
                    print("   Would you like to teach me? (yes/no)")

                    try:
                        answer = input("   > ").strip().lower()
                        if answer in ['yes', 'y', 'yeah', 'sure']:
                            start_url = f"https://www.{info['site']}/" if info['site'] else None
                            agent = self.learner.learn_task(info['task'], info['site'], start_url)

                            if agent:
                                # Now execute it
                                params = {
                                    "recipient": info.get("recipient", ""),
                                    "message": info.get("message", ""),
                                }
                                result = self.learner.execute_agent(agent, params)
                                if result.get("success"):
                                    return f"✓ Task complete! I've learned this for next time."
                                else:
                                    return f"✗ Learned but execution failed: {result.get('error')}"

                        return "OK, let me know when you want to teach me."

                    except (EOFError, KeyboardInterrupt):
                        return "Learning cancelled."

            # Fallback: use Claude's agentic loop (from v12)
            return self.fallback_agentic_loop(request)

        # Local task
        self.log("MODE", "Local task")
        return self.handle_local_task(request)

    def fallback_agentic_loop(self, request: str) -> str:
        """Fallback to Claude-driven agentic loop if no agent exists"""
        # This uses the v12-style approach as a fallback
        return "✗ No learned agent and agentic fallback not implemented in v13. Use 'learn' to teach me!"

    def handle_imessage(self, request: str) -> str:
        """Handle iMessage"""
        patterns = [
            r'(?:send\s+)?(?:i?message|text)\s+(?:to\s+)?["\']?(\w+)["\']?\s+(?:saying|with|:)?\s*["\']?(.+?)["\']?$',
            r'(?:message|text)\s+(\w+)\s+(.+)',
        ]

        recipient = message = None
        for pattern in patterns:
            match = re.search(pattern, request, re.IGNORECASE)
            if match:
                recipient, message = match.groups()[:2]
                break

        if not recipient:
            words = request.lower()
            for prefix in ['text ', 'message ', 'imessage ']:
                if prefix in words:
                    rest = words.split(prefix, 1)[1].strip()
                    parts = rest.split(' ', 1)
                    recipient = parts[0]
                    message = parts[1] if len(parts) > 1 else "Hey"
                    break

        if not recipient:
            return "✗ Could not parse recipient. Try: 'text john saying hello'"

        recipient = recipient.strip('"\'')
        message = (message or "Hey").strip('"\'')

        tool = self.local_tools.get("send_imessage")
        result = tool.execute(recipient=recipient, message=message)

        if result.get("verified"):
            return f"✓ Message sent to {result.get('recipient')}: \"{message}\""
        elif result.get("sent"):
            return f"✓ Message sent (unverified) to {result.get('recipient')}"
        return f"✗ Failed: {result.get('error', 'unknown')}"

    def handle_local_task(self, request: str) -> str:
        """Handle local task with Claude"""
        response = self.claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{"role": "user", "content": f"Request: {request}\n\nTools: {self.local_tools.list_tools()}\n\nReturn JSON: {{\"tool\": \"name\", \"params\": {{}}}} or {{\"response\": \"answer\"}}"}]
        )

        result_text = response.content[0].text.strip()
        try:
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0]
            action = json.loads(result_text)
            if "response" in action:
                return action["response"]
            tool = self.local_tools.get(action.get("tool"))
            if tool:
                result = tool.execute(**action.get("params", {}))
                if result.get("success"):
                    return "✓ Done"
                return f"✗ Failed: {result.get('error')}"
            return "✗ Unknown tool"
        except Exception as e:
            return f"✗ Error: {e}"

    # =========================================================================
    # STATUS & HELP
    # =========================================================================

    def get_status(self) -> str:
        """Show current status"""
        lines = [f"ClawdBot v{VERSION} Status", "=" * 40]

        # Browser
        if self.browser:
            lines.append("✓ Browser: Connected to Comet")
        else:
            lines.append("✗ Browser: Not available")

        # Observer
        if self.observer:
            state = self.observer.state
            lines.append(f"✓ Observer: {len(state.get('browser_tabs', []))} tabs known")
            lines.append(f"  Logged in: {', '.join(state.get('logged_in_sites', []))}")
        else:
            lines.append("✗ Observer: Not available")

        # Learner
        if self.learner:
            agents = self.learner.list_agents()
            lines.append(f"✓ Learner: {len(agents)} agents learned")
        else:
            lines.append("✗ Learner: Not available")

        return "\n".join(lines)

    def get_help(self) -> str:
        agent_count = len(self.learner.list_agents()) if self.learner else 0
        return f"""ClawdBot v{VERSION} - Learn by Watching

I OBSERVE and LEARN instead of guessing!

COMMANDS:
  discover     - Explore your system (tabs, logins, contacts)
  learn TASK   - Learn how to do a task interactively
  agents       - List all learned task agents
  status       - Show current status

TASKS (using learned agents):
  "send dm to abeer on instagram saying hi"
  "follow @user on instagram"
  "text muhlis saying hello"

LEARNED AGENTS: {agent_count}
  Type 'agents' to see what I know how to do.
  Type 'learn send_dm' to teach me something new.

Type 'quit' to exit.
"""


# =============================================================================
# MAIN
# =============================================================================

def main():
    print(f"""
╔═══════════════════════════════════════════════════════════╗
║  ClawdBot v{VERSION} - Learn by Watching                      ║
║  I OBSERVE and LEARN instead of guessing!                 ║
╚═══════════════════════════════════════════════════════════╝
""")

    # Handle CLI args
    if len(sys.argv) > 1:
        cmd = sys.argv[1]

        bot = ClawdBot()

        if cmd == "--discover":
            bot.discover_system()
            return

        elif cmd == "--learn" and len(sys.argv) > 2:
            task = sys.argv[2]
            site = sys.argv[3] if len(sys.argv) > 3 else ""
            url = sys.argv[4] if len(sys.argv) > 4 else None
            bot.learn_task(task, site, url)
            return

        elif cmd == "--agents":
            bot.list_agents()
            return

        elif cmd == "--status":
            print(bot.get_status())
            return

        else:
            print("Usage:")
            print("  python clawdbot_v13.py                    # Interactive mode")
            print("  python clawdbot_v13.py --discover         # Discover system")
            print("  python clawdbot_v13.py --learn TASK       # Learn a task")
            print("  python clawdbot_v13.py --agents           # List agents")
            print("  python clawdbot_v13.py --status           # Show status")
            return

    # Interactive mode
    bot = ClawdBot()

    # Show quick status
    if bot.learner:
        agents = bot.learner.list_agents()
        if agents:
            print(f"📚 {len(agents)} learned agents ready")
        else:
            print("💡 No agents yet. Type 'discover' to explore your system.")

    while True:
        try:
            user_input = input("\n🦞 You: ").strip()
            if not user_input:
                continue

            result = bot.process(user_input)

            if result == "EXIT":
                print("\n👋 Goodbye!")
                break

            if result:
                print(f"\n🤖 ClawdBot:\n{result}")

        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!")
            break
        except EOFError:
            break


if __name__ == "__main__":
    main()
