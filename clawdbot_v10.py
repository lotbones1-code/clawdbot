#!/usr/bin/env python3
"""
ClawdBot v10.0 - TRUE JARVIS Mode
=================================
Agentic Loop: SENSE → THINK → ACT → VERIFY → REPEAT

Unlike v9 which plans everything upfront and hopes it works,
v10 takes ONE action at a time, SEES the result (screenshot),
and DECIDES what to do next based on what it actually sees.

This is real intelligence: feedback loops, not batch execution.

Architecture:
- AgenticLoop: The core SENSE→THINK→ACT loop
- Vision: Claude sees screenshots after every action
- StepByStep: One action at a time, informed by results
- SmartTools: Browser tools + local macOS tools
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

VERSION = "10.0"
MAX_STEPS = 30  # Safety limit for agentic loop

# =============================================================================
# TOOL REGISTRY (same as v9 but streamlined)
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


class ToolRegistry:
    """Registry of all available tools"""

    def __init__(self):
        self.tools: Dict[str, Tool] = {}
        self._browser = None
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
        """Register all tools"""

        # --- Local macOS Tools ---

        self.register(Tool(
            name="bash",
            description="Run a shell command. Params: command (string)",
            execute=lambda **kw: self._run_bash(kw.get("command"))
        ))

        self.register(Tool(
            name="applescript",
            description="Run AppleScript to control macOS apps. Params: script (string)",
            execute=lambda **kw: self._run_applescript(kw.get("script"))
        ))

        self.register(Tool(
            name="open_url",
            description="Open a URL in default browser. Params: url (string)",
            execute=lambda **kw: self._open_url(kw.get("url"))
        ))

        self.register(Tool(
            name="open_app",
            description="Launch a macOS application. Params: app_name (string)",
            execute=lambda **kw: self._open_app(kw.get("app_name"))
        ))

        self.register(Tool(
            name="send_imessage",
            description="Send an iMessage. Params: recipient (name/phone), message (text)",
            execute=lambda **kw: self._send_imessage(kw.get("recipient"), kw.get("message"))
        ))

        # --- Browser Tools (v10 enhanced) ---

        if BROWSER_AVAILABLE:
            self._browser = get_browser()

            self.register(Tool(
                name="browser_navigate",
                description="Navigate browser to URL. Params: url (string)",
                execute=lambda **kw: self._browser_navigate(kw.get("url"))
            ))

            self.register(Tool(
                name="browser_click",
                description="Click an element. Params: target (text/button name to click)",
                execute=lambda **kw: self._browser_click(kw.get("target"))
            ))

            self.register(Tool(
                name="browser_click_nth",
                description="Click the Nth element. Params: target (text), index (0-based number)",
                execute=lambda **kw: self._browser_click_nth(kw.get("target"), kw.get("index", 0))
            ))

            self.register(Tool(
                name="browser_type",
                description="Type text. Params: text (what to type), field (optional: which field)",
                execute=lambda **kw: self._browser_type(kw.get("text"), kw.get("field"))
            ))

            self.register(Tool(
                name="browser_press",
                description="Press a key. Params: key (Enter, Tab, Escape, etc)",
                execute=lambda **kw: self._browser_press(kw.get("key"))
            ))

            self.register(Tool(
                name="browser_scroll",
                description="Scroll the page. Params: direction (up/down), amount (pixels, default 500)",
                execute=lambda **kw: self._browser_scroll(kw.get("direction", "down"), kw.get("amount", 500))
            ))

    # --- Tool Implementations ---

    def _run_bash(self, command: str) -> Dict:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
        return {"stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode}

    def _run_applescript(self, script: str) -> Dict:
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=30)
        return {"output": result.stdout.strip(), "error": result.stderr.strip() if result.returncode != 0 else None}

    def _open_url(self, url: str) -> Dict:
        if not url.startswith("http"):
            url = "https://" + url
        subprocess.run(["open", url], capture_output=True)
        return {"opened": url}

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

    # --- Browser Tool Implementations ---

    def _browser_navigate(self, url: str) -> Dict:
        return self._browser.navigate(url)

    def _browser_click(self, target: str) -> Dict:
        return self._browser.click(target)

    def _browser_click_nth(self, target: str, index: int) -> Dict:
        return self._browser.click_nth(target, int(index))

    def _browser_type(self, text: str, field: str = None) -> Dict:
        return self._browser.type_text(text, field)

    def _browser_press(self, key: str) -> Dict:
        return self._browser.press_key(key)

    def _browser_scroll(self, direction: str, amount: int) -> Dict:
        return self._browser.scroll(direction, int(amount))


# =============================================================================
# AGENTIC LOOP - The Core Intelligence
# =============================================================================

class AgenticLoop:
    """
    The SENSE → THINK → ACT loop that makes ClawdBot truly intelligent.

    Instead of planning everything upfront, we:
    1. SENSE: Take screenshot, read page state
    2. THINK: Ask Claude "what's the ONE next action?"
    3. ACT: Execute that single action
    4. VERIFY: Check result, repeat until goal achieved
    """

    def __init__(self, claude_client, tools: ToolRegistry, browser: BrowserController):
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

        for step in range(MAX_STEPS):
            # 1. SENSE - Get current state
            self.log("SENSE", f"Step {step + 1}: Taking screenshot...")

            screenshot_data = self.browser.screenshot_base64()
            if not screenshot_data.get("success"):
                # If no browser connected, try connecting
                if self.browser.connect():
                    screenshot_data = self.browser.screenshot_base64()

            page_text = ""
            if self.browser.is_connected():
                page_data = self.browser.read_page()
                page_text = page_data.get("content", "")[:3000]

            # 2. THINK - Ask Claude what to do next
            self.log("THINK", "Asking Claude for next action...")

            action = self.decide_next_action(
                goal=goal,
                screenshot=screenshot_data.get("image"),
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
                    "action": action,
                    "result": {"success": False, "error": f"Unknown tool: {tool_name}"}
                })
                continue

            result = tool.execute(**params)

            # 4. RECORD - Store for next iteration
            history.append({
                "step": step + 1,
                "action": action,
                "result": result
            })

            if result.get("success"):
                self.log("OK", f"Success: {json.dumps(result)[:100]}")
            else:
                self.log("FAIL", f"Failed: {result.get('error', 'unknown')}")

            # Small delay to let page update
            time.sleep(0.5)

        # Max steps reached
        return {
            "success": False,
            "message": f"Reached max steps ({MAX_STEPS}) without completing goal",
            "steps": len(history)
        }

    def decide_next_action(self, goal: str, screenshot: str, page_text: str, history: List) -> Dict:
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

        # Add the prompt
        history_text = ""
        if history:
            recent = history[-5:]  # Last 5 actions
            history_text = "\n".join([
                f"  {h['step']}. {h['action'].get('tool')}: {h['result'].get('success', False)}"
                for h in recent
            ])

        prompt = f"""GOAL: {goal}

CURRENT PAGE TEXT (truncated):
{page_text[:2000] if page_text else "[No page loaded yet]"}

PREVIOUS ACTIONS:
{history_text if history_text else "[None yet - this is the first action]"}

AVAILABLE TOOLS:
{self.tools.list_tools()}

Looking at this screenshot (if visible) and page content, what is the ONE next action to get closer to the goal?

IMPORTANT RULES:
1. Take ONE action at a time - you'll see the result and decide the next step
2. If you need to navigate somewhere first, do that
3. If you see the goal is ALREADY ACHIEVED, say done
4. Be specific with click targets (exact button text)

If the goal is ACHIEVED, respond:
{{"done": true, "summary": "what was accomplished"}}

Otherwise respond with ONE action:
{{"tool": "tool_name", "params": {{"param": "value"}}, "reason": "why this action"}}

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
            # If parsing fails, try to extract JSON
            import re
            json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            return {"tool": "browser_navigate", "params": {"url": "about:blank"}, "reason": "Parse error, resetting"}


# =============================================================================
# CLAWDBOT v10 - Main Agent
# =============================================================================

class ClawdBot:
    """
    ClawdBot v10 - TRUE JARVIS Mode

    For browser tasks: Uses AgenticLoop (SENSE→THINK→ACT)
    For local tasks: Direct tool execution
    """

    def __init__(self):
        self.claude = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        self.tools = ToolRegistry()
        self.browser = get_browser() if BROWSER_AVAILABLE else None
        self.agentic = AgenticLoop(self.claude, self.tools, self.browser) if self.browser else None

    def log(self, tag: str, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"{ts} [{tag:8}] {msg}")

    def needs_browser(self, request: str) -> bool:
        """Determine if request needs browser automation"""
        request_lower = request.lower()
        browser_keywords = [
            'instagram', 'twitter', 'x.com', 'facebook', 'youtube',
            'follow', 'like', 'post', 'tweet', 'browse', 'website',
            'search', 'google', 'click', 'navigate', 'login', 'sign in'
        ]
        return any(kw in request_lower for kw in browser_keywords)

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

        # Determine approach
        if self.needs_browser(request) and self.agentic:
            self.log("MODE", "Using Agentic Loop (browser task)")
            result = self.agentic.run(request)

            if result.get("success"):
                return f"✓ {result.get('summary', 'Done!')}\n  (Completed in {result.get('steps', 0)} steps)"
            else:
                return f"✗ {result.get('message', 'Could not complete')}"

        else:
            # Local task - use simple reasoning
            self.log("MODE", "Direct execution (local task)")
            return self.handle_local_task(request)

    def handle_local_task(self, request: str) -> str:
        """Handle non-browser tasks directly"""

        # Ask Claude how to handle this
        response = self.claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{
                "role": "user",
                "content": f"""User request: {request}

Available tools:
{self.tools.list_tools()}

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

            tool = self.tools.get(action.get("tool"))
            if tool:
                result = tool.execute(**action.get("params", {}))
                if result.get("success"):
                    # Format output nicely
                    output = result.get("output", result)
                    if isinstance(output, dict):
                        if output.get("verified"):
                            return f"✓ Message sent and verified to {output.get('recipient')}"
                        elif output.get("sent"):
                            return f"✓ Message sent to {output.get('recipient')}"
                        elif output.get("opened"):
                            return f"✓ Opened: {output.get('opened')}"
                        elif output.get("stdout"):
                            return f"✓ Output:\n{output.get('stdout')}"
                    return f"✓ Done: {json.dumps(output)[:200]}"
                else:
                    return f"✗ Failed: {result.get('error', 'unknown')}"

            return f"✗ Unknown tool: {action.get('tool')}"

        except Exception as e:
            return f"✗ Error: {e}"

    def get_help(self) -> str:
        browser_status = "✓ Agentic browser mode enabled" if self.agentic else "✗ Browser not available"
        return f"""ClawdBot v{VERSION} - TRUE JARVIS Mode
{browser_status}

WHAT'S NEW IN v10:
• Agentic Loop: I SEE what happens after each action
• Vision: I look at screenshots, not just text
• Adaptive: I figure out next steps based on what I see
• Smart: If something fails, I try alternatives

BROWSER TASKS (I'll figure it out step by step):
  "follow 5 people on instagram"
  "like some posts on twitter"
  "search youtube for lofi and play the first video"
  "post a tweet saying hello world"

LOCAL TASKS:
  "send hi to john on imessage"
  "what time is it"
  "open spotify"

I'll show you my thought process as I work.
Type 'quit' to exit.
"""


# =============================================================================
# MAIN
# =============================================================================

def main():
    print(f"""
╔═══════════════════════════════════════════════════════════╗
║  ClawdBot v{VERSION} - TRUE JARVIS Mode                        ║
║  I SEE, I THINK, I ACT. One step at a time.               ║
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
