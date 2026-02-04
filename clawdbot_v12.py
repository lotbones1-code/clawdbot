#!/usr/bin/env python3
"""
ClawdBot v12 - JARVIS Mode with Persistent System Knowledge
============================================================
THE FUNDAMENTAL CHANGE: ClawdBot now LEARNS and REMEMBERS.

Knowledge System:
- Loads ~/.clawdbot/system_knowledge.json on startup
- Contains site-specific workflows (HOW to do things on Instagram, Twitter, etc.)
- Tracks learned failures (what NOT to do)
- Updates after successes and failures
- Asks user when stuck, saves their answer

Key Features:
1. KNOWLEDGE-FIRST: Before any task, check if we know how to do it
2. WORKFLOW FOLLOWING: If we have a workflow, follow it step by step
3. FAILURE AVOIDANCE: Never repeat known failed approaches
4. LEARNING: Record successes and failures for next time
5. USER ASSISTANCE: Ask user when stuck, save their answer

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

# Import browser controller
try:
    from browser_cdp import get_browser_cdp, BrowserCDP
    BROWSER_AVAILABLE = True
except ImportError:
    BROWSER_AVAILABLE = False

# Import knowledge manager
try:
    from knowledge_manager import KnowledgeManager
    KNOWLEDGE_AVAILABLE = True
except ImportError:
    KNOWLEDGE_AVAILABLE = False
    print("⚠ Knowledge manager not available")

# =============================================================================
# CONFIG
# =============================================================================

CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY") or open(
    os.path.expanduser("~/clawdbot-v2/.env")
).read().split("CLAUDE_API_KEY=")[1].split("\n")[0]

VERSION = "12.0"
MAX_STEPS = 15  # Fail fast
LOOP_THRESHOLD = 3  # Detect loops after 3 repeated failures


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
# AGENTIC TOOL REGISTRY
# =============================================================================

class AgenticToolRegistry:
    """Browser tools only - no open_url/open_app that break the loop"""

    def __init__(self, browser: BrowserCDP):
        self.tools: Dict[str, Tool] = {}
        self._browser = browser
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
            name="navigate",
            description="Go to a URL. Params: url",
            execute=lambda **kw: self._browser.navigate(kw.get("url"))
        ))

        self.register(Tool(
            name="click",
            description="Click element by text. Params: target",
            execute=lambda **kw: self._browser.click(kw.get("target"))
        ))

        self.register(Tool(
            name="click_nth",
            description="Click Nth matching element. Params: target, index (0-based)",
            execute=lambda **kw: self._browser.click_nth(kw.get("target"), int(kw.get("index", 0)))
        ))

        self.register(Tool(
            name="type",
            description="Type text. Params: text, field (optional)",
            execute=lambda **kw: self._browser.type_text(kw.get("text"), kw.get("field"))
        ))

        self.register(Tool(
            name="press",
            description="Press key. Params: key (Enter, Tab, Escape, etc.)",
            execute=lambda **kw: self._browser.press_key(kw.get("key"))
        ))

        self.register(Tool(
            name="wait",
            description="Wait N seconds. Params: seconds (default 2). Use after typing to wait for dropdowns.",
            execute=lambda **kw: self._wait(int(kw.get("seconds", 2)))
        ))

        self.register(Tool(
            name="scroll",
            description="Scroll page. Params: direction (up/down), amount (pixels, default 500)",
            execute=lambda **kw: self._browser.scroll(kw.get("direction", "down"), int(kw.get("amount", 500)))
        ))

        self.register(Tool(
            name="scroll_find",
            description="Scroll looking for text. Params: text. For finding people in lists.",
            execute=lambda **kw: self._browser.scroll_find(kw.get("text"), int(kw.get("max_scrolls", 15)))
        ))

    def _wait(self, seconds: int) -> Dict:
        time.sleep(seconds)
        return {"success": True, "waited": f"{seconds} seconds"}


# =============================================================================
# LOCAL TOOL REGISTRY
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
        self.register(Tool(
            name="bash",
            description="Run shell command. Params: command",
            execute=lambda **kw: self._run_bash(kw.get("command"))
        ))

        self.register(Tool(
            name="open_app",
            description="Open macOS app. Params: app_name",
            execute=lambda **kw: self._open_app(kw.get("app_name"))
        ))

        self.register(Tool(
            name="send_imessage",
            description="Send iMessage. Params: recipient, message",
            execute=lambda **kw: self._send_imessage(kw.get("recipient"), kw.get("message"))
        ))

    def _run_bash(self, command: str) -> Dict:
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

        return {
            "sent": True,
            "verified": after_max > before_max,
            "recipient": actual_recipient,
            "message": message
        }


# =============================================================================
# LOOP DETECTOR
# =============================================================================

class LoopDetector:
    """Detects when Claude is stuck repeating failed actions"""

    def __init__(self, threshold: int = LOOP_THRESHOLD):
        self.threshold = threshold
        self.action_history: List[str] = []

    def add_action(self, tool: str, params: Dict, success: bool):
        signature = f"{tool}:{json.dumps(params, sort_keys=True)}:{success}"
        self.action_history.append(signature)

    def is_looping(self) -> bool:
        if len(self.action_history) < self.threshold:
            return False

        recent = self.action_history[-self.threshold:]
        if len(set(recent)) == 1 and recent[0].endswith(":False"):
            return True

        recent_5 = self.action_history[-5:] if len(self.action_history) >= 5 else []
        if recent_5:
            unique = set(recent_5)
            if len(unique) <= 2 and all(a.endswith(":False") for a in recent_5):
                return True

        return False

    def get_loop_summary(self) -> str:
        if not self.action_history:
            return "No actions"
        recent = self.action_history[-5:]
        counter = Counter(recent)
        most_common = counter.most_common(1)[0]
        return f"'{most_common[0].split(':')[0]}' repeated {most_common[1]}x"

    def get_last_failed_action(self) -> Optional[str]:
        """Get the last failed action for learning"""
        for sig in reversed(self.action_history):
            if sig.endswith(":False"):
                parts = sig.rsplit(":", 2)
                return parts[0] if parts else None
        return None

    def reset(self):
        self.action_history = []


# =============================================================================
# AGENTIC LOOP - Knowledge-Aware
# =============================================================================

class AgenticLoop:
    """
    The SENSE → THINK → ACT loop with KNOWLEDGE INTEGRATION.

    Before acting:
    1. Check knowledge for existing workflow
    2. Check knowledge for failures to avoid
    3. Include both in Claude's prompt

    After acting:
    4. Record successes (increase confidence)
    5. Record failures (add to learned_failures)
    6. Ask user if stuck (save their answer)
    """

    def __init__(self, claude_client, tools: AgenticToolRegistry, browser: BrowserCDP,
                 knowledge: KnowledgeManager = None):
        self.claude = claude_client
        self.tools = tools
        self.browser = browser
        self.knowledge = knowledge
        self.loop_detector = LoopDetector()

    def log(self, tag: str, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"{ts} [{tag:8}] {msg}")

    def run(self, goal: str) -> Dict:
        """Execute the agentic loop with knowledge"""
        history = []
        self.loop_detector.reset()
        self.log("GOAL", goal)

        # =====================================================================
        # KNOWLEDGE-FIRST: What do we know about this task?
        # =====================================================================
        site = ""
        task = ""
        workflow = None
        failures_to_avoid = []

        if self.knowledge:
            site = self.knowledge.extract_site_from_goal(goal)
            task = self.knowledge.extract_task_from_goal(goal)

            if site and task:
                workflow = self.knowledge.get_site_workflow(site, task)
                failures_to_avoid = self.knowledge.get_failures_for_task(site, task)

                if workflow:
                    self.log("KNOWLEDGE", f"Found workflow for '{task}' on {site}")
                    self.log("KNOWLEDGE", f"Confidence: {workflow.get('confidence', 0):.0%}")

                if failures_to_avoid:
                    self.log("KNOWLEDGE", f"Avoiding {len(failures_to_avoid)} known failure(s)")

        # Ensure browser connected
        if not self.browser.connect():
            return {"success": False, "message": "Could not connect to browser"}

        # =====================================================================
        # THE LOOP
        # =====================================================================
        for step in range(MAX_STEPS):
            self.log("SENSE", f"Step {step + 1}/{MAX_STEPS}")

            screenshot_data = self.browser.screenshot_base64()
            current_url = screenshot_data.get("url", "about:blank")
            page_title = screenshot_data.get("title", "")

            page_data = self.browser.read_page()
            page_text = page_data.get("content", "")[:2000]

            # Check for loops
            loop_warning = ""
            if self.loop_detector.is_looping():
                self.log("LOOP!", self.loop_detector.get_loop_summary())

                # LEARN FROM FAILURE
                if self.knowledge and site:
                    failed_action = self.loop_detector.get_last_failed_action()
                    if failed_action:
                        self.knowledge.record_failure(
                            site=site,
                            task=task,
                            wrong_approach=failed_action,
                            why_failed="Repeated failure in loop"
                        )

                loop_warning = f"""
⚠️ LOOP DETECTED! You've repeated the same failing action {LOOP_THRESHOLD}+ times.
The current approach is NOT WORKING. Try something DIFFERENT:
- If Enter didn't work, try CLICKING instead
- If clicking text failed, try different element
- If nothing works, give up with explanation

DO NOT repeat the same action!
"""

            # THINK
            self.log("THINK", "Deciding next action...")

            action = self.decide_next_action(
                goal=goal,
                screenshot=screenshot_data.get("image"),
                current_url=current_url,
                page_title=page_title,
                page_text=page_text,
                history=history,
                workflow=workflow,
                failures_to_avoid=failures_to_avoid,
                loop_warning=loop_warning
            )

            # Done?
            if action.get("done"):
                self.log("DONE", action.get("summary", "Goal achieved!"))

                # LEARN FROM SUCCESS
                if self.knowledge and site and task:
                    successful_steps = [h["action"] for h in history if h["result"].get("success")]
                    self.knowledge.record_success(site, task, successful_steps)
                    self.knowledge.save()

                return {"success": True, "summary": action.get("summary"), "steps": len(history)}

            # Giving up?
            if action.get("give_up"):
                reason = action.get("reason", "Cannot complete")
                self.log("GIVEUP", reason)

                # Learn from giving up
                if self.knowledge and site and task:
                    self.knowledge.record_workflow_failure(site, task)
                    self.knowledge.save()

                return {"success": False, "message": reason, "steps": len(history)}

            # ACT
            tool_name = action.get("tool")
            params = action.get("params", {})
            reason = action.get("reason", "")

            self.log("ACT", f"{tool_name}: {reason}")

            tool = self.tools.get(tool_name)
            if not tool:
                self.log("ERROR", f"Unknown tool: {tool_name}")
                history.append({"step": step + 1, "action": action,
                               "result": {"success": False, "error": f"Unknown tool"}})
                self.loop_detector.add_action(tool_name, params, False)
                continue

            result = tool.execute(**params)

            history.append({"step": step + 1, "action": action, "result": result})
            self.loop_detector.add_action(tool_name, params, result.get("success", False))

            if result.get("success"):
                self.log("OK", f"Success")
            else:
                self.log("FAIL", f"Failed: {result.get('error', '?')[:50]}")

            time.sleep(1)

        # Max steps
        if self.knowledge:
            self.knowledge.record_workflow_failure(site, task)
            self.knowledge.save()

        return {"success": False, "message": f"Max steps ({MAX_STEPS}) reached", "steps": len(history)}

    def decide_next_action(self, goal: str, screenshot: str, current_url: str,
                           page_title: str, page_text: str, history: List,
                           workflow: Dict = None, failures_to_avoid: List = None,
                           loop_warning: str = "") -> Dict:
        """Ask Claude what to do, with knowledge included"""

        content = []

        if screenshot:
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": screenshot}
            })

        # Build history text
        history_text = ""
        if history:
            recent = history[-5:]
            history_text = "\n".join([
                f"  {h['step']}. {h['action'].get('tool')}({h['action'].get('params', {})}) → "
                f"{'✓' if h['result'].get('success') else '✗ ' + h['result'].get('error', '')[:40]}"
                for h in recent
            ])

        # Build workflow text
        workflow_text = ""
        if workflow:
            steps = workflow.get("steps", [])
            workflow_text = f"""
═══════════════════════════════════════════════════════════════════════════════
✓ KNOWN WORKFLOW (follow these steps EXACTLY):
═══════════════════════════════════════════════════════════════════════════════
Confidence: {workflow.get('confidence', 0):.0%}
"""
            for i, step in enumerate(steps, 1):
                action = step.get("action", "?")
                note = step.get("note", "")
                target = step.get("target", step.get("value", step.get("url", "")))
                workflow_text += f"{i}. {action.upper()}: {target}"
                if note:
                    workflow_text += f" ({note})"
                workflow_text += "\n"

        # Build failures text
        failures_text = ""
        if failures_to_avoid:
            failures_text = "\n⚠️ AVOID THESE KNOWN FAILURES:\n"
            for f in failures_to_avoid:
                wrong = f.get("wrong_approach", "?")
                correct = f.get("correct_approach", "")
                failures_text += f"  ✗ DON'T: {wrong}\n"
                if correct:
                    failures_text += f"    ✓ INSTEAD: {correct}\n"

        # THE PROMPT
        prompt = f"""You are JARVIS - an intelligent AI assistant with LEARNED KNOWLEDGE about this user's computer.

{workflow_text}
{failures_text}
{loop_warning}

═══════════════════════════════════════════════════════════════════════════════
GOAL: {goal}
═══════════════════════════════════════════════════════════════════════════════

CURRENT STATE:
• URL: {current_url}
• Title: {page_title}
• Page text: {page_text[:800] if page_text else "[Empty]"}

PREVIOUS ACTIONS:
{history_text if history_text else "[None yet]"}

TOOLS:
{self.tools.list_tools()}

═══════════════════════════════════════════════════════════════════════════════
INSTRUCTIONS:
1. If there's a KNOWN WORKFLOW above, follow it step by step
2. If there are KNOWN FAILURES, avoid those approaches
3. Look at the screenshot to see what's on screen
4. Take ONE action that moves toward the goal
5. If goal is achieved, respond with done
6. If you're stuck after trying multiple approaches, give up with explanation

RESPONSES (JSON only):

Goal achieved:
{{"done": true, "summary": "what was done"}}

Cannot complete:
{{"give_up": true, "reason": "why impossible"}}

Next action:
{{"tool": "name", "params": {{"key": "value"}}, "reason": "why"}}

JSON:"""

        content.append({"type": "text", "text": prompt})

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
            json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except:
                    pass
            return {"give_up": True, "reason": "Could not parse response"}


# =============================================================================
# CLAWDBOT v12
# =============================================================================

class ClawdBot:
    """
    ClawdBot v12 - JARVIS with Persistent Knowledge

    WHAT'S NEW:
    - Loads ~/.clawdbot/system_knowledge.json on startup
    - Checks knowledge BEFORE tasks
    - Follows known workflows step-by-step
    - Avoids known failures
    - Learns from successes and failures
    """

    def __init__(self):
        self.claude = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        self.browser = get_browser_cdp() if BROWSER_AVAILABLE else None

        # LOAD KNOWLEDGE
        self.knowledge = KnowledgeManager() if KNOWLEDGE_AVAILABLE else None
        if self.knowledge:
            self.knowledge.print_summary()

        self.agentic_tools = AgenticToolRegistry(self.browser) if self.browser else None
        self.local_tools = LocalToolRegistry()

        self.agentic = AgenticLoop(
            self.claude,
            self.agentic_tools,
            self.browser,
            self.knowledge  # Pass knowledge to agentic loop
        ) if self.browser else None

    def log(self, tag: str, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"{ts} [{tag:8}] {msg}")

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
        if 'send' in r and ('saying' in r or ' to ' in r):
            return True
        return False

    def needs_browser(self, request: str) -> bool:
        kw = ['instagram', 'twitter', 'x.com', 'facebook', 'youtube', 'linkedin',
              'follow', 'like', 'post', 'tweet', 'browse', 'website', 'web',
              'search google', 'click', 'navigate', 'login', 'sign in', 'dm',
              'message on instagram', 'message on twitter', 'on ig', 'on insta']
        return any(k in request.lower() for k in kw)

    def handle_imessage(self, request: str) -> str:
        patterns = [
            r'(?:send\s+)?(?:i?message|text)\s+(?:to\s+)?["\']?(\w+)["\']?\s+(?:saying|with|:)?\s*["\']?(.+?)["\']?$',
            r'(?:send|text)\s+["\'](.+?)["\']\s+to\s+(\w+)',
            r'(?:tell|ask)\s+(\w+)\s+(.+)',
            r'(?:message|text)\s+(\w+)\s+(.+)',
        ]

        recipient = message = None
        for pattern in patterns:
            match = re.search(pattern, request, re.IGNORECASE)
            if match:
                g1, g2 = match.groups()[:2]
                if ' ' in g1 and ' ' not in g2:
                    recipient, message = g2, g1
                else:
                    recipient, message = g1, g2
                break

        if not recipient:
            words = request.lower()
            for prefix in ['text to ', 'message to ', 'text ', 'message ', 'imessage ']:
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

        self.log("IMESSAGE", f"To: {recipient}, Message: {message}")

        tool = self.local_tools.get("send_imessage")
        result = tool.execute(recipient=recipient, message=message)

        if result.get("verified"):
            return f"✓ Message sent and verified to {result.get('recipient')}: \"{message}\""
        elif result.get("sent"):
            return f"✓ Message sent to {result.get('recipient')}: \"{message}\""
        return f"✗ Failed: {result.get('error', 'unknown')}"

    def process(self, request: str) -> str:
        text = request.lower().strip()
        if not text:
            return None
        if text in ['quit', 'exit', 'q']:
            return "EXIT"
        if text in ['help', '?']:
            return self.get_help()
        if text == 'knowledge':
            if self.knowledge:
                self.knowledge.print_summary()
                return "Knowledge summary printed above."
            return "Knowledge manager not available."

        if self.needs_imessage(request):
            self.log("MODE", "iMessage")
            return self.handle_imessage(request)

        if self.needs_browser(request) and self.agentic:
            self.log("MODE", "Agentic browser (v12 with knowledge)")
            result = self.agentic.run(request)
            if result.get("success"):
                return f"✓ {result.get('summary', 'Done!')}\n  (Completed in {result.get('steps', 0)} steps)"
            return f"✗ {result.get('message', 'Could not complete')}"

        self.log("MODE", "Local task")
        return self.handle_local_task(request)

    def handle_local_task(self, request: str) -> str:
        response = self.claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{"role": "user", "content": f"""Request: {request}

Tools: {self.local_tools.list_tools()}

Return JSON:
{{"tool": "name", "params": {{}}}} or {{"response": "answer"}}

JSON:"""}]
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
                    if result.get("verified"):
                        return f"✓ Message sent and verified"
                    if result.get("opened"):
                        return f"✓ Opened: {result.get('opened')}"
                    if result.get("stdout"):
                        return f"✓ Output:\n{result.get('stdout')}"
                    return "✓ Done"
                return f"✗ Failed: {result.get('error', 'unknown')}"
            return f"✗ Unknown tool"
        except Exception as e:
            return f"✗ Error: {e}"

    def get_help(self) -> str:
        browser_status = "✓ Browser ready" if self.agentic else "✗ No browser"
        knowledge_status = "✓ Knowledge loaded" if self.knowledge else "✗ No knowledge"
        return f"""ClawdBot v{VERSION} - JARVIS with Persistent Knowledge

{browser_status}
{knowledge_status}

WHAT'S NEW IN v12:
• PERSISTENT KNOWLEDGE - Loads ~/.clawdbot/system_knowledge.json
• WORKFLOW FOLLOWING - Knows HOW to do tasks on Instagram, Twitter
• FAILURE AVOIDANCE - Won't repeat known mistakes
• LEARNING - Gets smarter over time

COMMANDS:
  "send message to abeer on instagram saying hi"
  "follow @user on instagram"
  "text muhlis saying hello"
  "knowledge" - show what I know
  "quit" - exit

Type 'knowledge' to see what I've learned.
"""


# =============================================================================
# MAIN
# =============================================================================

def main():
    print(f"""
╔═══════════════════════════════════════════════════════════╗
║  ClawdBot v{VERSION} - JARVIS with Persistent Knowledge        ║
║  I LEARN from your computer and get SMARTER over time     ║
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
