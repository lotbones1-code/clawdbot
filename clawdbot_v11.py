#!/usr/bin/env python3
"""
ClawdBot v11.2 - JARVIS Mode with Loop Detection & Site Knowledge
==================================================================
FIXES:
1. LOOP DETECTION: Detects repeated failed actions, tries different approach
2. SITE KNOWLEDGE: Knows HOW Instagram DMs work (don't press Enter, click dropdown)
3. SMART MAX STEPS: 15 steps max, not 35 infinite loops

Uses direct Chrome DevTools Protocol (CDP) via websockets.
NO MORE PLAYWRIGHT HANGING on browsers with many tabs!

SETUP: Start Comet with: /Applications/Comet.app/Contents/MacOS/Comet --remote-debugging-port=9222
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
from collections import Counter

import anthropic

# Import browser controller - USE CDP (direct websocket) instead of Playwright
try:
    from browser_cdp import get_browser_cdp, BrowserCDP
    BROWSER_AVAILABLE = True
except ImportError:
    BROWSER_AVAILABLE = False

# =============================================================================
# CONFIG
# =============================================================================

CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY") or open(
    os.path.expanduser("~/clawdbot-v2/.env")
).read().split("CLAUDE_API_KEY=")[1].split("\n")[0]

VERSION = "11.2"
MAX_STEPS = 15  # Reduced from 35 - fail fast, don't loop forever
LOOP_THRESHOLD = 3  # If same action fails 3 times, force different approach


# =============================================================================
# SITE-SPECIFIC KNOWLEDGE
# =============================================================================

SITE_KNOWLEDGE = """
═══════════════════════════════════════════════════════════════════════════════
CRITICAL SITE-SPECIFIC KNOWLEDGE (follow these EXACTLY):
═══════════════════════════════════════════════════════════════════════════════

INSTAGRAM DMs - How to send a message:
1. Click the Messages icon (paper airplane) in left sidebar OR bottom-right floating button
2. Click "New message" or the compose/pen icon (creates new conversation)
3. In the "To:" field, type the recipient's name (do NOT press Enter!)
4. WAIT 2-3 seconds for the dropdown results to auto-populate
5. CLICK on the person's name in the dropdown list (do NOT press Enter!)
6. Click "Chat" or "Next" to open the conversation
7. Type your message in the "Message..." input field at the bottom
8. Press Enter or click Send to send

IMPORTANT FOR INSTAGRAM:
- NEVER press Enter after typing a name in search - it doesn't work like Google
- ALWAYS wait for autocomplete dropdown, then CLICK the result
- If you don't see the person, try searching their full username

TWITTER/X DMs:
1. Click the Messages icon in the sidebar
2. Click the "New message" icon
3. Search for the person (type their name/username)
4. CLICK on their name from results (don't press Enter)
5. Type message and send

GOOGLE SEARCH:
- Type in search box, THEN press Enter (this one does need Enter)

YOUTUBE:
- Type in search box, press Enter OR click search button
"""


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
    Uses BrowserCDP (direct websocket) instead of Playwright.
    """

    def __init__(self, browser: BrowserCDP):
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

        # Navigate to URL
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
            description="Press a keyboard key. Params: key (Enter, Tab, Escape, Backspace, etc.). WARNING: On Instagram search, do NOT press Enter - wait and click the result instead!",
            execute=lambda **kw: self._browser.press_key(kw.get("key"))
        ))

        # Wait for something to appear
        self.register(Tool(
            name="wait",
            description="Wait for specific text to appear OR just wait N seconds. Params: text (optional), seconds (default 2). Use after typing to wait for dropdown results.",
            execute=lambda **kw: self._wait_helper(kw.get("text"), kw.get("seconds", 2))
        ))

        # Scroll
        self.register(Tool(
            name="scroll",
            description="Scroll the page. Params: direction (up/down), amount (pixels, default 500)",
            execute=lambda **kw: self._browser.scroll(kw.get("direction", "down"), int(kw.get("amount", 500)))
        ))

        # Scroll and Find (for infinite scroll lists)
        self.register(Tool(
            name="scroll_find",
            description="Scroll down a list looking for specific text. Params: text (what to find). Use for finding someone in followers/following lists.",
            execute=lambda **kw: self._browser.scroll_find(kw.get("text"), int(kw.get("max_scrolls", 15)))
        ))

    def _wait_helper(self, text: str = None, seconds: int = 2) -> Dict:
        """Wait for text or just wait N seconds"""
        if text:
            return self._browser.wait_for_text(text, timeout=seconds * 1000)
        else:
            time.sleep(seconds)
            return {"success": True, "waited": f"{seconds} seconds"}


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
# LOOP DETECTOR - Prevents infinite loops
# =============================================================================

class LoopDetector:
    """
    Detects when Claude is stuck in a loop repeating the same failed action.
    Forces it to try a different approach.
    """

    def __init__(self, threshold: int = LOOP_THRESHOLD):
        self.threshold = threshold
        self.action_history: List[str] = []

    def add_action(self, tool: str, params: Dict, success: bool):
        """Record an action"""
        # Create a signature for this action
        signature = f"{tool}:{json.dumps(params, sort_keys=True)}:{success}"
        self.action_history.append(signature)

    def is_looping(self) -> bool:
        """Check if we're stuck in a loop"""
        if len(self.action_history) < self.threshold:
            return False

        # Get last N actions
        recent = self.action_history[-self.threshold:]

        # Check if they're all the same AND all failed
        if len(set(recent)) == 1 and recent[0].endswith(":False"):
            return True

        # Also check if last N actions are alternating between same 2-3 failed actions
        recent_5 = self.action_history[-5:] if len(self.action_history) >= 5 else []
        if recent_5:
            unique_actions = set(recent_5)
            # If only 1-2 unique actions repeated 5 times, all failing
            if len(unique_actions) <= 2 and all(a.endswith(":False") for a in recent_5):
                return True

        return False

    def get_loop_summary(self) -> str:
        """Describe what's being repeated"""
        if not self.action_history:
            return "No actions yet"

        recent = self.action_history[-5:]
        counter = Counter(recent)
        most_common = counter.most_common(1)[0]
        return f"Action '{most_common[0].split(':')[0]}' repeated {most_common[1]} times"

    def reset(self):
        """Clear history"""
        self.action_history = []


# =============================================================================
# AGENTIC LOOP - The Core Intelligence (FIXED with Loop Detection)
# =============================================================================

class AgenticLoop:
    """
    The SENSE → THINK → ACT loop with:
    1. LOOP DETECTION - Stops repeating failed actions
    2. SITE KNOWLEDGE - Knows HOW Instagram/Twitter work
    3. SMART MAX STEPS - 15 steps, not 35
    """

    def __init__(self, claude_client, tools: AgenticToolRegistry, browser: BrowserCDP):
        self.claude = claude_client
        self.tools = tools
        self.browser = browser
        self.loop_detector = LoopDetector()

    def log(self, tag: str, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"{ts} [{tag:8}] {msg}")

    def run(self, goal: str) -> Dict:
        """Execute the agentic loop until goal is achieved"""
        history = []
        self.loop_detector.reset()
        self.log("GOAL", goal)

        # Ensure browser is connected
        if not self.browser.connect():
            return {"success": False, "message": "Could not connect to browser"}

        for step in range(MAX_STEPS):
            # 1. SENSE - Get current state
            self.log("SENSE", f"Step {step + 1}/{MAX_STEPS}: Taking screenshot...")

            screenshot_data = self.browser.screenshot_base64()
            current_url = screenshot_data.get("url", "about:blank")
            page_title = screenshot_data.get("title", "")

            page_data = self.browser.read_page()
            page_text = page_data.get("content", "")[:2500]

            # 2. CHECK FOR LOOPS
            if self.loop_detector.is_looping():
                self.log("LOOP!", f"Detected loop: {self.loop_detector.get_loop_summary()}")
                # Force Claude to try different approach
                loop_warning = f"""
⚠️ LOOP DETECTED! You've repeated the same failing action {LOOP_THRESHOLD}+ times.
The current approach is NOT WORKING. You MUST try something different:
- If pressing Enter didn't work, try CLICKING instead
- If clicking text didn't work, try clicking a different element
- If search didn't work, try navigating directly to a profile URL
- If nothing works, explain WHY and give up

DO NOT repeat the same action again!
"""
            else:
                loop_warning = ""

            # 3. THINK - Ask Claude what to do next
            self.log("THINK", "Asking Claude for next action...")

            action = self.decide_next_action(
                goal=goal,
                screenshot=screenshot_data.get("image"),
                current_url=current_url,
                page_title=page_title,
                page_text=page_text,
                history=history,
                loop_warning=loop_warning
            )

            # Check if done
            if action.get("done"):
                self.log("DONE", action.get("summary", "Goal achieved!"))
                return {
                    "success": True,
                    "summary": action.get("summary"),
                    "steps": len(history)
                }

            # Check if giving up
            if action.get("give_up"):
                self.log("GIVEUP", action.get("reason", "Cannot complete task"))
                return {
                    "success": False,
                    "message": action.get("reason", "Cannot complete task"),
                    "steps": len(history)
                }

            # 4. ACT - Execute the action
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
                self.loop_detector.add_action(tool_name, params, False)
                continue

            result = tool.execute(**params)

            # 5. RECORD
            history.append({
                "step": step + 1,
                "action": action,
                "result": result
            })

            # Track for loop detection
            self.loop_detector.add_action(tool_name, params, result.get("success", False))

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
                           page_title: str, page_text: str, history: List,
                           loop_warning: str = "") -> Dict:
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
                f"  {h['step']}. {h['action'].get('tool')}({h['action'].get('params', {})}) → {'✓' if h['result'].get('success') else '✗ ' + h['result'].get('error', '')[:50]}"
                for h in recent
            ])

        # THE IMPROVED PROMPT with site knowledge and loop detection
        prompt = f"""You are JARVIS - an intelligent AI assistant controlling a web browser via CDP.

{SITE_KNOWLEDGE}

═══════════════════════════════════════════════════════════════════════════════
GOAL: {goal}
═══════════════════════════════════════════════════════════════════════════════

CURRENT STATE:
• URL: {current_url}
• Title: {page_title}
• Page text (truncated): {page_text[:1000] if page_text else "[Empty or loading]"}

PREVIOUS ACTIONS (last 5):
{history_text if history_text else "[None yet - this is the first step]"}

{loop_warning}

AVAILABLE TOOLS:
{self.tools.list_tools()}

═══════════════════════════════════════════════════════════════════════════════
INSTRUCTIONS:
1. Look at the screenshot to understand what's currently visible
2. If on Instagram and need to DM someone:
   - Click Messages icon first
   - Then "New message"
   - Type name, WAIT for dropdown (use "wait" tool), then CLICK the name
   - NEVER press Enter after typing a name in Instagram search!
3. If an action failed, try a DIFFERENT approach, not the same thing
4. If you truly cannot complete the task, give up with explanation

RESPONSES (return ONLY valid JSON):

If goal achieved:
{{"done": true, "summary": "what was accomplished"}}

If cannot complete (after trying different approaches):
{{"give_up": true, "reason": "why it's impossible"}}

Otherwise, ONE action:
{{"tool": "tool_name", "params": {{"param": "value"}}, "reason": "why this moves toward goal"}}

JSON only:"""

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
            # Fallback
            return {"give_up": True, "reason": "Could not parse Claude's response"}


# =============================================================================
# CLAWDBOT v11.2 - Main Agent
# =============================================================================

class ClawdBot:
    """
    ClawdBot v11.2 - JARVIS Mode with Loop Detection & Site Knowledge

    FIXES:
    1. Loop detection - won't repeat same failed action 35 times
    2. Site knowledge - knows HOW Instagram DMs work
    3. Smart max steps - 15 steps, fail fast
    """

    def __init__(self):
        self.claude = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        self.browser = get_browser_cdp() if BROWSER_AVAILABLE else None

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
                    g1, g2 = groups[0], groups[1]
                    if ' ' in g1 and ' ' not in g2:
                        recipient, message = g2, g1
                    else:
                        recipient, message = g1, g2
                    break

        if not recipient:
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

        recipient = recipient.strip('"\'')
        message = message.strip('"\'') if message else "Hey"

        self.log("IMESSAGE", f"To: {recipient}, Message: {message}")

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

        text = request.lower().strip()
        if not text:
            return None
        if text in ['quit', 'exit', 'q']:
            return "EXIT"
        if text in ['help', '?']:
            return self.get_help()

        # CHECK iMESSAGE FIRST
        if self.needs_imessage(request):
            self.log("MODE", "iMessage mode (local)")
            return self.handle_imessage(request)

        # Then browser
        if self.needs_browser(request) and self.agentic:
            self.log("MODE", "Agentic browser mode (v11.2 with loop detection)")
            result = self.agentic.run(request)

            if result.get("success"):
                return f"✓ {result.get('summary', 'Done!')}\n  (Completed in {result.get('steps', 0)} steps)"
            else:
                return f"✗ {result.get('message', 'Could not complete')}"

        else:
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
        browser_status = "✓ Browser ready (connects to Comet)" if self.agentic else "✗ Browser not available"
        return f"""ClawdBot v{VERSION} - JARVIS Mode with Loop Detection

{browser_status}

WHAT'S NEW IN v11.2:
• LOOP DETECTION - Won't repeat same failed action forever
• SITE KNOWLEDGE - Knows HOW Instagram DMs work
• SMART STEPS - Max 15 steps, fail fast don't loop

BROWSER TASKS:
  "send message to abeer on instagram saying hi"
  "follow @username on instagram"
  "search youtube for lofi and play it"

IMESSAGE TASKS:
  "text muhlis saying hello"
  "imessage john hey whats up"

Type 'quit' to exit.
"""


# =============================================================================
# MAIN
# =============================================================================

def main():
    print(f"""
╔═══════════════════════════════════════════════════════════╗
║  ClawdBot v{VERSION} - JARVIS Mode                            ║
║  NOW WITH: Loop Detection + Site Knowledge                ║
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
