#!/usr/bin/env python3
"""
ClawdBot v11.1 - JARVIS Mode with Comet Browser
===============================================
Fixes the v10 loop bug + connects to Comet browser (saved sessions!)

Key Changes:
1. AGENTIC-ONLY TOOLS: No open_url/open_app in browser mode
2. COMET FIRST: Connects to Comet browser where you're logged in
3. IMESSAGE ROUTING: "text john" goes to iMessage, "dm john on insta" goes browser
4. SCROLL_FIND: Can scroll through lists to find people (Instagram followers)

Architecture:
- AgenticLoop: SENSE → THINK → ACT → VERIFY → REPEAT
- Vision: Claude sees screenshots after every action
- Browser-Only Tools: navigate, click, type, scroll, scroll_find
"""

import os
import re
import json
import sqlite3
import subprocess
import time
import base64
from datetime import datetime
from typing import Dict, List, Any, Optional, Callable

import anthropic

# Import browser controller
try:
    from browser import get_browser, BrowserController
    BROWSER_AVAILABLE = True
except ImportError:
    BROWSER_AVAILABLE = False

# =============================================================================
# CONFIG
# =============================================================================

CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY") or open(
    os.path.expanduser("~/clawdbot-v2/.env")
).read().split("CLAUDE_API_KEY=")[1].split("\n")[0]

VERSION = "11.1"
MAX_STEPS = 35  # More steps for complex tasks

# =============================================================================
# TOOL CLASS
# =============================================================================

class Tool:
    """A tool that Claude can use"""
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
# AGENTIC TOOL REGISTRY - Browser Tools ONLY
# =============================================================================

class AgenticToolRegistry:
    """
    Tools for AGENTIC browser mode ONLY.
    NO open_url, NO open_app - those break the loop!
    """

    def __init__(self, browser: BrowserController):
        self.tools: Dict[str, Tool] = {}
        self._browser = browser
        self._register_tools()

    def register(self, tool: Tool):
        self.tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self.tools.get(name)

    def list_tools(self) -> str:
        """Format tools for Claude's context"""
        lines = []
        for name, tool in self.tools.items():
            lines.append(f"- {name}: {tool.description}")
        return "\n".join(lines)

    def _register_tools(self):
        """Register ONLY browser tools - no Safari/macOS tools"""

        # Navigate to URL (THE way to go to websites)
        self.register(Tool(
            name="navigate",
            description="Go to a URL. Params: url (string). This loads the page in YOUR browser.",
            execute=lambda **kw: self._browser.navigate(kw.get("url"))
        ))

        # Click on element
        self.register(Tool(
            name="click",
            description="Click on an element by its text. Params: target (the text to click, e.g. 'Follow', 'Message', 'Profile')",
            execute=lambda **kw: self._browser.click(kw.get("target"))
        ))

        # Click nth element (for multiple matches)
        self.register(Tool(
            name="click_nth",
            description="Click the Nth element matching text. Params: target (text), index (0-based). Use when there are multiple buttons/links with same text.",
            execute=lambda **kw: self._browser.click_nth(kw.get("target"), int(kw.get("index", 0)))
        ))

        # Type text
        self.register(Tool(
            name="type",
            description="Type text into the current field or search box. Params: text (what to type), field (optional: field name/placeholder)",
            execute=lambda **kw: self._browser.type_text(kw.get("text"), kw.get("field"))
        ))

        # Press key
        self.register(Tool(
            name="press",
            description="Press a keyboard key. Params: key (Enter, Tab, Escape, Backspace, etc.)",
            execute=lambda **kw: self._browser.press_key(kw.get("key"))
        ))

        # Scroll
        self.register(Tool(
            name="scroll",
            description="Scroll the page. Params: direction (up/down), amount (pixels, default 500)",
            execute=lambda **kw: self._browser.scroll(kw.get("direction", "down"), int(kw.get("amount", 500)))
        ))

        # Scroll and Find (for infinite scroll lists like Instagram followers)
        self.register(Tool(
            name="scroll_find",
            description="Scroll down a list looking for specific text. Params: text (what to find). Use for finding someone in followers/following lists.",
            execute=lambda **kw: self._browser.scroll_find(kw.get("text"), int(kw.get("max_scrolls", 15)))
        ))

        # Wait for text
        self.register(Tool(
            name="wait",
            description="Wait for specific text to appear. Params: text (what to wait for). Use after clicking to ensure page loaded.",
            execute=lambda **kw: self._browser.wait_for_text(kw.get("text"), int(kw.get("timeout", 10000)))
        ))


# =============================================================================
# LOCAL TOOL REGISTRY - For non-browser tasks
# =============================================================================

class LocalToolRegistry:
    """Tools for LOCAL macOS tasks (iMessage, apps, bash)"""

    def __init__(self):
        self.tools: Dict[str, Tool] = {}
        self._register_tools()

    def register(self, tool: Tool):
        self.tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self.tools.get(name)

    def list_tools(self) -> str:
        lines = []
        for name, tool in self.tools.items():
            lines.append(f"- {name}: {tool.description}")
        return "\n".join(lines)

    def _register_tools(self):
        self.register(Tool(
            name="bash",
            description="Run a shell command. Params: command (string)",
            execute=lambda **kw: self._run_bash(kw.get("command"))
        ))

        self.register(Tool(
            name="open_app",
            description="Open a macOS application. Params: app_name (string)",
            execute=lambda **kw: self._open_app(kw.get("app_name"))
        ))

        self.register(Tool(
            name="send_imessage",
            description="Send an iMessage. Params: recipient (name/phone), message (text)",
            execute=lambda **kw: self._send_imessage(kw.get("recipient"), kw.get("message"))
        ))

    def _run_bash(self, command: str) -> Dict:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
        return {"stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode}

    def _open_app(self, app_name: str) -> Dict:
        subprocess.run(["open", "-a", app_name], capture_output=True)
        return {"opened": app_name}

    def _send_imessage(self, recipient: str, message: str) -> Dict:
        """Send iMessage with database verification"""
        db_path = os.path.expanduser("~/Library/Messages/chat.db")

        # Find recipient
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM handle WHERE LOWER(id) LIKE ?",
                (f"%{recipient.lower()}%",)
            )
            matches = cursor.fetchall()
            conn.close()

            if not matches:
                return {"sent": False, "error": f"Contact '{recipient}' not found"}

            actual_recipient = matches[0][0]
        except Exception as e:
            return {"sent": False, "error": str(e)}

        # Get message count before
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(ROWID) FROM message")
        before_max = cursor.fetchone()[0] or 0
        conn.close()

        # Send
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

        # Verify
        time.sleep(1)
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(ROWID) FROM message")
        after_max = cursor.fetchone()[0] or 0
        conn.close()

        return {
            "sent": True,
            "verified": after_max > before_max,
            "recipient": actual_recipient,
            "message": message
        }


# =============================================================================
# AGENTIC LOOP - The Core Intelligence (FIXED)
# =============================================================================

class AgenticLoop:
    """
    The SENSE → THINK → ACT loop with FIXED prompt.

    Key fix: The prompt now CLEARLY explains that:
    1. Screenshots come from YOUR Playwright browser
    2. Use 'navigate' tool to go to URLs (not open_url)
    3. Multi-step reasoning for complex tasks
    """

    def __init__(self, claude_client, tools: AgenticToolRegistry, browser: BrowserController):
        self.claude = claude_client
        self.tools = tools
        self.browser = browser

    def log(self, tag: str, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"{ts} [{tag:8}] {msg}")

    def run(self, goal: str) -> Dict:
        """Execute the agentic loop until goal is achieved"""
        history = []
        self.log("GOAL", goal)

        # Ensure browser is connected
        if not self.browser.connect():
            return {"success": False, "message": "Could not connect to browser"}

        for step in range(MAX_STEPS):
            # 1. SENSE - Get current state
            self.log("SENSE", f"Step {step + 1}: Taking screenshot...")

            screenshot_data = self.browser.screenshot_base64()
            current_url = screenshot_data.get("url", "about:blank")
            page_title = screenshot_data.get("title", "")

            page_data = self.browser.read_page()
            page_text = page_data.get("content", "")[:2500]

            # 2. THINK - Ask Claude what to do next
            self.log("THINK", "Asking Claude for next action...")

            action = self.decide_next_action(
                goal=goal,
                screenshot=screenshot_data.get("image"),
                current_url=current_url,
                page_title=page_title,
                page_text=page_text,
                history=history
            )

            # Check if done
            if action.get("done"):
                self.log("DONE", action.get("summary", "Goal achieved!"))
                return {
                    "success": True,
                    "summary": action.get("summary"),
                    "steps": len(history)
                }

            # 3. ACT - Execute the action
            tool_name = action.get("tool")
            params = action.get("params", {})
            reason = action.get("reason", "")

            self.log("ACT", f"{tool_name}: {reason}")

            tool = self.tools.get(tool_name)
            if not tool:
                self.log("ERROR", f"Unknown tool: {tool_name}")
                history.append({
                    "step": step + 1,
                    "action": action,
                    "result": {"success": False, "error": f"Unknown tool: {tool_name}"}
                })
                continue

            result = tool.execute(**params)

            # 4. RECORD
            history.append({
                "step": step + 1,
                "action": action,
                "result": result
            })

            if result.get("success"):
                self.log("OK", f"Success: {json.dumps(result)[:80]}")
            else:
                self.log("FAIL", f"Failed: {result.get('error', 'unknown')}")

            # Wait for page to update
            time.sleep(1)

        # Max steps reached
        return {
            "success": False,
            "message": f"Reached max steps ({MAX_STEPS}) without completing goal",
            "steps": len(history)
        }

    def decide_next_action(self, goal: str, screenshot: str, current_url: str,
                           page_title: str, page_text: str, history: List) -> Dict:
        """Ask Claude with vision: what's the ONE next action?"""

        # Build message content
        content = []

        # Add screenshot if available
        if screenshot:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": screenshot
                }
            })

        # Build history text
        history_text = ""
        if history:
            recent = history[-5:]
            history_text = "\n".join([
                f"  {h['step']}. {h['action'].get('tool')}({h['action'].get('params', {})}) → {'✓' if h['result'].get('success') else '✗'}"
                for h in recent
            ])

        # THE FIXED PROMPT - explains browser context clearly
        prompt = f"""You are JARVIS - an intelligent AI assistant controlling a Playwright web browser.

═══════════════════════════════════════════════════════════════════════════════
CRITICAL: The screenshot above shows YOUR browser window.
To visit a website, use the "navigate" tool - this loads the page in YOUR browser.
═══════════════════════════════════════════════════════════════════════════════

GOAL: {goal}

CURRENT STATE:
• URL: {current_url}
• Title: {page_title}
• Page text (truncated): {page_text[:1500] if page_text else "[Empty or loading]"}

PREVIOUS ACTIONS:
{history_text if history_text else "[None yet - this is the first step]"}

AVAILABLE TOOLS:
{self.tools.list_tools()}

═══════════════════════════════════════════════════════════════════════════════
INSTRUCTIONS:
1. Look at the screenshot to understand what's currently on screen
2. Think about what ONE action moves you closer to the goal
3. For complex tasks (like finding someone on Instagram), break it down:
   - First navigate to the site
   - Then find the right section (profile, followers, etc.)
   - Then search/scroll to find what you need
   - Then take the action (message, follow, etc.)

If the goal is ALREADY ACHIEVED, respond:
{{"done": true, "summary": "what was accomplished"}}

Otherwise respond with ONE action:
{{"tool": "tool_name", "params": {{"param": "value"}}, "reason": "why this moves toward the goal"}}

Return ONLY valid JSON, nothing else:"""

        content.append({"type": "text", "text": prompt})

        # Call Claude with vision
        response = self.claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{"role": "user", "content": content}]
        )

        result_text = response.content[0].text.strip()

        # Parse JSON
        if "```json" in result_text:
            result_text = result_text.split("```json")[1].split("```")[0]
        elif "```" in result_text:
            result_text = result_text.split("```")[1].split("```")[0]

        try:
            return json.loads(result_text)
        except:
            # Try to extract JSON
            json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except:
                    pass
            # Fallback - something went wrong
            return {"tool": "navigate", "params": {"url": "about:blank"}, "reason": "Parse error, resetting"}


# =============================================================================
# CLAWDBOT v11 - Main Agent
# =============================================================================

class ClawdBot:
    """
    ClawdBot v11 - JARVIS Mode Fixed

    For browser tasks: Uses AgenticLoop with BROWSER-ONLY tools
    For local tasks: Uses LocalToolRegistry
    """

    def __init__(self):
        self.claude = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        self.browser = get_browser() if BROWSER_AVAILABLE else None

        # Separate tool registries
        self.agentic_tools = AgenticToolRegistry(self.browser) if self.browser else None
        self.local_tools = LocalToolRegistry()

        # Agentic loop for browser tasks
        self.agentic = AgenticLoop(self.claude, self.agentic_tools, self.browser) if self.browser else None

    def log(self, tag: str, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"{ts} [{tag:8}] {msg}")

    def needs_imessage(self, request: str) -> bool:
        """Check if this is an iMessage/text request (NOT Instagram DM)"""
        r = request.lower()

        # Social platforms that mean browser, not iMessage
        social = ['instagram', 'twitter', 'facebook', 'linkedin', 'discord', 'whatsapp', 'on ig', 'on insta', 'on twitter']

        # If any social platform is mentioned, NOT iMessage
        if any(p in r for p in social):
            return False

        # Explicit iMessage triggers
        if 'imessage' in r or 'text message' in r:
            return True

        # "text X" (like "text muhlis saying hello")
        if r.startswith('text ') or ' text ' in r:
            return True

        # "message X" without social platform (already checked above)
        if 'message' in r and (' to ' in r or r.startswith('message ')):
            return True

        # "send X to Y" patterns (without social platform)
        if 'send' in r and ('saying' in r or ' to ' in r):
            return True

        return False

    def needs_browser(self, request: str) -> bool:
        """Determine if request needs browser automation"""
        request_lower = request.lower()
        browser_keywords = [
            'instagram', 'twitter', 'x.com', 'facebook', 'youtube', 'linkedin',
            'follow', 'like', 'post', 'tweet', 'browse', 'website', 'web',
            'search google', 'click', 'navigate', 'login', 'sign in', 'dm',
            'message on instagram', 'message on twitter', 'on ig', 'on insta'
        ]
        return any(kw in request_lower for kw in browser_keywords)

    def handle_imessage(self, request: str) -> str:
        """Handle iMessage directly without Claude routing"""

        # Parse: various patterns
        patterns = [
            r'(?:send\s+)?(?:i?message|text)\s+(?:to\s+)?["\']?(\w+)["\']?\s+(?:saying|with|:)?\s*["\']?(.+?)["\']?$',
            r'(?:send|text)\s+["\'](.+?)["\']\s+to\s+(\w+)',
            r'(?:tell|ask)\s+(\w+)\s+(.+)',
            r'(?:message|text)\s+(\w+)\s+(.+)',
        ]

        recipient = None
        message = None

        for pattern in patterns:
            match = re.search(pattern, request, re.IGNORECASE)
            if match:
                groups = match.groups()
                if len(groups) >= 2:
                    # Check which group is name vs message
                    g1, g2 = groups[0], groups[1]
                    # If first group looks like a message (has spaces), swap
                    if ' ' in g1 and ' ' not in g2:
                        recipient, message = g2, g1
                    else:
                        recipient, message = g1, g2
                    break

        if not recipient:
            # Simple extraction: "text john hello" or "message muhlis hi"
            words = request.lower()
            for prefix in ['send text to ', 'text to ', 'message to ', 'imessage to ', 'text ', 'message ', 'imessage ']:
                if prefix in words:
                    rest = words.split(prefix, 1)[1].strip()
                    parts = rest.split(' ', 1)
                    recipient = parts[0]
                    message = parts[1] if len(parts) > 1 else "Hey"
                    break

        if not recipient:
            return "✗ Could not parse recipient. Try: 'text john saying hello'"

        # Clean up
        recipient = recipient.strip('"\'')
        message = message.strip('"\'') if message else "Hey"

        self.log("IMESSAGE", f"To: {recipient}, Message: {message}")

        # Use the local tool
        tool = self.local_tools.get("send_imessage")
        if tool:
            result = tool.execute(recipient=recipient, message=message)
            if result.get("verified"):
                return f"✓ Message sent and verified to {result.get('recipient')}: \"{message}\""
            elif result.get("sent"):
                return f"✓ Message sent to {result.get('recipient')}: \"{message}\""
            else:
                return f"✗ Failed: {result.get('error', 'unknown')}"

        return "✗ iMessage tool not available"

    def process(self, request: str) -> str:
        """Process any request"""

        # Built-in commands
        text = request.lower().strip()
        if not text:
            return None
        if text in ['quit', 'exit', 'q']:
            return "EXIT"
        if text in ['help', '?']:
            return self.get_help()

        # CHECK iMESSAGE FIRST (before browser!)
        if self.needs_imessage(request):
            self.log("MODE", "iMessage mode (local)")
            return self.handle_imessage(request)

        # Then browser
        if self.needs_browser(request) and self.agentic:
            self.log("MODE", "Agentic browser mode (v11.1)")
            result = self.agentic.run(request)

            if result.get("success"):
                return f"✓ {result.get('summary', 'Done!')}\n  (Completed in {result.get('steps', 0)} steps)"
            else:
                return f"✗ {result.get('message', 'Could not complete')}"

        else:
            # Local task
            self.log("MODE", "Local task mode")
            return self.handle_local_task(request)

    def handle_local_task(self, request: str) -> str:
        """Handle non-browser tasks"""

        response = self.claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{
                "role": "user",
                "content": f"""User request: {request}

Available tools:
{self.local_tools.list_tools()}

What tool should I use? Return JSON:
{{"tool": "tool_name", "params": {{}}, "reason": "why"}}

Or if this doesn't need a tool:
{{"response": "just answer the question"}}

Return ONLY JSON:"""
            }]
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
                    output = result
                    if output.get("verified"):
                        return f"✓ Message sent and verified to {output.get('recipient')}"
                    elif output.get("sent"):
                        return f"✓ Message sent to {output.get('recipient')}"
                    elif output.get("opened"):
                        return f"✓ Opened: {output.get('opened')}"
                    elif output.get("stdout"):
                        return f"✓ Output:\n{output.get('stdout')}"
                    return f"✓ Done"
                else:
                    return f"✗ Failed: {result.get('error', 'unknown')}"

            return f"✗ Unknown tool: {action.get('tool')}"

        except Exception as e:
            return f"✗ Error: {e}"

    def get_help(self) -> str:
        browser_status = "✓ Browser ready (connects to Comet for saved logins)" if self.agentic else "✗ Browser not available"
        return f"""ClawdBot v{VERSION} - JARVIS Mode with Comet
{browser_status}

WHAT'S NEW IN v11.1:
• Connects to Comet browser first (saved Instagram/Twitter logins!)
• Smart routing: "text john" → iMessage, "dm john on insta" → Browser
• scroll_find - Can search through followers/following lists
• No more loop bugs

BROWSER TASKS (uses Comet with your logins):
  "send message to abeer on instagram saying hi"
  "follow 5 people on instagram"
  "search youtube for lofi and play it"
  "like some posts on twitter"

IMESSAGE TASKS (local):
  "text muhlis saying hello"
  "imessage john hey whats up"
  "message halit hi"

OTHER LOCAL TASKS:
  "open spotify"
  "what time is it"

SETUP: Start Comet with debug port for saved sessions:
  /Applications/Comet.app/Contents/MacOS/Comet --remote-debugging-port=9222 &

Type 'quit' to exit.
"""


# =============================================================================
# MAIN
# =============================================================================

def main():
    print(f"""
╔═══════════════════════════════════════════════════════════╗
║  ClawdBot v{VERSION} - JARVIS Mode with Comet                  ║
║  Connects to YOUR browser. Uses YOUR logins.              ║
╚═══════════════════════════════════════════════════════════╝
""")

    bot = ClawdBot()

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
