#!/usr/bin/env python3
"""
ClawdBot v9.0 - JARVIS Mode
============================
Full browser automation + reasoning = can do ANYTHING.

Like JARVIS from Iron Man - you speak, it does.
Not "I opened the page" but "I followed 5 people on Instagram."

Architecture:
1. Tool Registry - Including BROWSER AUTOMATION tools
2. Reasoner - Claude figures out HOW to do anything
3. Executor - Run tools, thread outputs between steps
4. Verifier - Actually check things worked
5. Recovery - Reflect on failures, try alternatives
6. Memory - Remember what works

New in v9:
- Browser navigation, clicking, typing
- Read page content
- Find elements by description
- Actually interact with websites (Instagram, Twitter, etc)
"""

import os
import re
import json
import sqlite3
import subprocess
import time
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

VERSION = "9.0"
MEMORY_FILE = os.path.expanduser("~/clawdbot-v2/memory.json")
MAX_RETRIES = 2

# =============================================================================
# TOOL REGISTRY
# =============================================================================

class Tool:
    """A composable tool that Claude can use"""
    def __init__(self, name: str, description: str,
                 execute: Callable, verify: Callable = None,
                 examples: List[str] = None):
        self.name = name
        self.description = description
        self._execute = execute
        self._verify = verify or (lambda r: r.get("success", False))
        self.examples = examples or []

    def execute(self, **params) -> Dict:
        """Run the tool and return result"""
        try:
            result = self._execute(**params)
            return {"success": True, "output": result}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def verify(self, result: Dict) -> bool:
        """Check if the tool execution actually worked"""
        return self._verify(result)


class ToolRegistry:
    """Registry of all available tools"""

    def __init__(self):
        self.tools: Dict[str, Tool] = {}
        self._register_builtin_tools()

    def register(self, tool: Tool):
        self.tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self.tools.get(name)

    def list_tools(self) -> str:
        """Format tools for Claude's context"""
        lines = []
        for name, tool in self.tools.items():
            lines.append(f"- {name}: {tool.description}")
            if tool.examples:
                for ex in tool.examples[:2]:
                    lines.append(f"    Example: {ex}")
        return "\n".join(lines)

    def _register_builtin_tools(self):
        """Register the core macOS tools"""

        # Bash - run any shell command
        self.register(Tool(
            name="bash",
            description="Run any shell command. Params: command (string). Returns stdout/stderr.",
            execute=lambda **kw: self._run_bash(kw.get("command")),
            verify=lambda r: r.get("success") and r.get("output", {}).get("returncode") == 0,
            examples=["ls -la", "date", "ps aux | grep Safari"]
        ))

        # AppleScript - control macOS apps
        self.register(Tool(
            name="applescript",
            description="Run AppleScript to control macOS apps. Params: script (string).",
            execute=lambda **kw: self._run_applescript(kw.get("script")),
            verify=lambda r: r.get("success"),
            examples=[
                'tell application "Spotify" to play',
                'tell application "Safari" to open location "https://google.com"'
            ]
        ))

        # Open URL - open in browser
        self.register(Tool(
            name="open_url",
            description="Open a URL in the default browser. Params: url (string).",
            execute=lambda **kw: self._open_url(kw.get("url")),
            verify=lambda r: r.get("success"),
            examples=["https://youtube.com", "https://x.com"]
        ))

        # Open App - launch application
        self.register(Tool(
            name="open_app",
            description="Open/launch a macOS application. Params: app_name (string).",
            execute=lambda **kw: self._open_app(kw.get("app_name")),
            verify=lambda r: r.get("success"),
            examples=["Spotify", "Safari", "Messages"]
        ))

        # Query SQLite - read app databases
        self.register(Tool(
            name="query_db",
            description="Query a SQLite database. Params: db_path (string), query (SQL string). Useful for Messages (~/Library/Messages/chat.db), Calendar, etc.",
            execute=lambda **kw: self._query_db(kw.get("db_path"), kw.get("query")),
            verify=lambda r: r.get("success") and r.get("output") is not None,
            examples=["SELECT * FROM handle WHERE id LIKE '%john%'"]
        ))

        # Read File
        self.register(Tool(
            name="read_file",
            description="Read contents of a file. Params: path (string).",
            execute=lambda **kw: self._read_file(kw.get("path")),
            verify=lambda r: r.get("success"),
            examples=["/etc/hosts", "~/.zshrc"]
        ))

        # Write File
        self.register(Tool(
            name="write_file",
            description="Write content to a file. Params: path (string), content (string).",
            execute=lambda **kw: self._write_file(kw.get("path"), kw.get("content")),
            verify=lambda r: r.get("success") and os.path.exists(r.get("output", {}).get("path", "")),
            examples=["Create test.txt with 'hello'"]
        ))

        # Check App Running
        self.register(Tool(
            name="check_app_running",
            description="Check if an app is currently running. Params: app_name (string).",
            execute=lambda **kw: self._check_app_running(kw.get("app_name")),
            verify=lambda r: r.get("success"),
            examples=["Spotify", "Safari"]
        ))

        # Get Running Apps
        self.register(Tool(
            name="get_running_apps",
            description="Get list of currently running applications. No params needed.",
            execute=lambda **kw: self._get_running_apps(),
            verify=lambda r: r.get("success"),
        ))

        # Send iMessage (with verification)
        self.register(Tool(
            name="send_imessage",
            description="Send an iMessage to a contact. Params: recipient (name/phone), message (text). Verifies delivery via Messages database.",
            execute=lambda **kwargs: self._send_imessage(kwargs.get("recipient"), kwargs.get("message")),
            verify=lambda r: r.get("success") and r.get("output", {}).get("verified"),
            examples=["send 'hello' to 'John'"]
        ))

        # =====================================================================
        # BROWSER AUTOMATION TOOLS (NEW IN v9)
        # =====================================================================

        if BROWSER_AVAILABLE:
            self._browser = get_browser()

            # Navigate to URL
            self.register(Tool(
                name="browser_navigate",
                description="Navigate browser to a URL. Params: url (string). Opens the page and waits for it to load.",
                execute=lambda **kw: self._browser_navigate(kw.get("url")),
                verify=lambda r: r.get("success"),
                examples=["https://instagram.com", "https://twitter.com"]
            ))

            # Read page content
            self.register(Tool(
                name="browser_read",
                description="Read the visible text content of the current page. Returns page title, URL, and text content.",
                execute=lambda **kw: self._browser_read(),
                verify=lambda r: r.get("success"),
            ))

            # Find elements on page
            self.register(Tool(
                name="browser_find",
                description="Find elements on the page. Params: description (what to find, e.g. 'Follow buttons', 'Login link', 'search input'). Returns list of matching elements.",
                execute=lambda **kw: self._browser_find(kw.get("description")),
                verify=lambda r: r.get("success"),
                examples=["Follow buttons", "Like buttons", "input fields"]
            ))

            # Click element
            self.register(Tool(
                name="browser_click",
                description="Click an element on the page. Params: target (text or description of what to click, e.g. 'Follow', 'Login', 'Post').",
                execute=lambda **kw: self._browser_click(kw.get("target")),
                verify=lambda r: r.get("success"),
                examples=["Follow", "Like", "Post", "Submit"]
            ))

            # Click nth element
            self.register(Tool(
                name="browser_click_nth",
                description="Click the Nth element matching target. Params: target (text), index (0-based). For clicking specific buttons when there are multiple.",
                execute=lambda **kw: self._browser_click_nth(kw.get("target"), kw.get("index", 0)),
                verify=lambda r: r.get("success"),
                examples=["Click 2nd Follow button"]
            ))

            # Type text
            self.register(Tool(
                name="browser_type",
                description="Type text into the focused element or a specific field. Params: text (what to type), field (optional: which field to target).",
                execute=lambda **kw: self._browser_type(kw.get("text"), kw.get("field")),
                verify=lambda r: r.get("success"),
                examples=["Type 'hello world' into search"]
            ))

            # Press key
            self.register(Tool(
                name="browser_press",
                description="Press a keyboard key. Params: key (e.g. 'Enter', 'Tab', 'Escape'). Useful for submitting forms or navigation.",
                execute=lambda **kw: self._browser_press(kw.get("key")),
                verify=lambda r: r.get("success"),
                examples=["Enter", "Tab", "Escape"]
            ))

            # Scroll page
            self.register(Tool(
                name="browser_scroll",
                description="Scroll the page. Params: direction ('up' or 'down'), amount (pixels, default 500).",
                execute=lambda **kw: self._browser_scroll(kw.get("direction", "down"), kw.get("amount", 500)),
                verify=lambda r: r.get("success"),
            ))

            # Wait for text
            self.register(Tool(
                name="browser_wait",
                description="Wait for specific text to appear on the page. Params: text (what to wait for), timeout (ms, default 10000).",
                execute=lambda **kw: self._browser_wait(kw.get("text"), kw.get("timeout", 10000)),
                verify=lambda r: r.get("success"),
            ))

    # --- Browser Tool Implementations ---

    def _browser_navigate(self, url: str) -> Dict:
        if not BROWSER_AVAILABLE:
            return {"error": "Browser not available"}
        return self._browser.navigate(url)

    def _browser_read(self) -> Dict:
        if not BROWSER_AVAILABLE:
            return {"error": "Browser not available"}
        return self._browser.read_page()

    def _browser_find(self, description: str) -> Dict:
        if not BROWSER_AVAILABLE:
            return {"error": "Browser not available"}
        return self._browser.find_elements(description)

    def _browser_click(self, target: str) -> Dict:
        if not BROWSER_AVAILABLE:
            return {"error": "Browser not available"}
        return self._browser.click(target)

    def _browser_click_nth(self, target: str, index: int) -> Dict:
        if not BROWSER_AVAILABLE:
            return {"error": "Browser not available"}
        return self._browser.click_nth(target, index)

    def _browser_type(self, text: str, field: str = None) -> Dict:
        if not BROWSER_AVAILABLE:
            return {"error": "Browser not available"}
        return self._browser.type_text(text, field)

    def _browser_press(self, key: str) -> Dict:
        if not BROWSER_AVAILABLE:
            return {"error": "Browser not available"}
        return self._browser.press_key(key)

    def _browser_scroll(self, direction: str, amount: int) -> Dict:
        if not BROWSER_AVAILABLE:
            return {"error": "Browser not available"}
        return self._browser.scroll(direction, amount)

    def _browser_wait(self, text: str, timeout: int) -> Dict:
        if not BROWSER_AVAILABLE:
            return {"error": "Browser not available"}
        return self._browser.wait_for_text(text, timeout)

    # --- Tool Implementations ---

    def _run_bash(self, command: str) -> Dict:
        result = subprocess.run(
            command, shell=True,
            capture_output=True, text=True, timeout=30
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode
        }

    def _run_applescript(self, script: str) -> Dict:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=30
        )
        return {
            "output": result.stdout.strip(),
            "error": result.stderr.strip() if result.returncode != 0 else None,
            "returncode": result.returncode
        }

    def _open_url(self, url: str) -> Dict:
        if not url.startswith("http"):
            url = "https://" + url
        result = subprocess.run(["open", url], capture_output=True)
        return {"url": url, "opened": result.returncode == 0}

    def _open_app(self, app_name: str) -> Dict:
        result = subprocess.run(["open", "-a", app_name], capture_output=True)
        return {"app": app_name, "opened": result.returncode == 0}

    def _query_db(self, db_path: str, query: str) -> Dict:
        db_path = os.path.expanduser(db_path)
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(query)
        results = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        conn.close()
        return {"columns": columns, "rows": results}

    def _read_file(self, path: str) -> Dict:
        path = os.path.expanduser(path)
        with open(path, 'r') as f:
            content = f.read()
        return {"path": path, "content": content}

    def _write_file(self, path: str, content: str) -> Dict:
        path = os.path.expanduser(path)
        with open(path, 'w') as f:
            f.write(content)
        return {"path": path, "written": True}

    def _check_app_running(self, app_name: str) -> Dict:
        result = subprocess.run(
            ["pgrep", "-x", app_name],
            capture_output=True
        )
        return {"app": app_name, "running": result.returncode == 0}

    def _get_running_apps(self) -> Dict:
        script = '''
        tell application "System Events"
            set appList to name of every process whose background only is false
            return appList
        end tell
        '''
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        apps = result.stdout.strip().split(", ") if result.stdout else []
        return {"apps": apps}

    def _send_imessage(self, recipient: str, message: str) -> Dict:
        """Send iMessage with verification"""
        db_path = os.path.expanduser("~/Library/Messages/chat.db")

        # Step 1: Find the recipient in Messages database
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM handle WHERE LOWER(id) = LOWER(?) OR LOWER(id) LIKE ?",
                (recipient, f"%{recipient.lower()}%")
            )
            matches = cursor.fetchall()
            conn.close()

            if not matches:
                return {
                    "sent": False,
                    "verified": False,
                    "error": f"Contact '{recipient}' not found in Messages"
                }

            actual_recipient = matches[0][0]
        except Exception as e:
            return {"sent": False, "verified": False, "error": f"DB error: {e}"}

        # Step 2: Get message count before sending
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(ROWID) FROM message")
            before_max = cursor.fetchone()[0] or 0
            conn.close()
        except:
            before_max = 0

        # Step 3: Send via AppleScript
        message_safe = message.replace('\\', '\\\\').replace('"', '\\"')
        recipient_safe = actual_recipient.replace('\\', '\\\\').replace('"', '\\"')

        script = f'''
        tell application "Messages"
            set targetService to 1st account whose service type = iMessage
            set targetBuddy to participant "{recipient_safe}" of targetService
            send "{message_safe}" to targetBuddy
        end tell
        '''

        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)

        # Step 4: Verify by checking if new message appeared
        time.sleep(1)

        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(ROWID) FROM message")
            after_max = cursor.fetchone()[0] or 0

            verified = after_max > before_max
            conn.close()

            return {
                "sent": True,
                "verified": verified,
                "recipient": actual_recipient,
                "message": message
            }
        except:
            return {
                "sent": result.returncode == 0,
                "verified": False,
                "recipient": actual_recipient,
                "message": message
            }


# =============================================================================
# MEMORY SYSTEM
# =============================================================================

class Memory:
    """Remembers what works and what doesn't"""

    def __init__(self):
        self.successes = {}  # task_pattern -> approach that worked
        self.failures = {}   # task_pattern -> approaches that failed
        self._load()

    def _load(self):
        try:
            if os.path.exists(MEMORY_FILE):
                with open(MEMORY_FILE, 'r') as f:
                    data = json.load(f)
                    self.successes = data.get("successes", {})
                    self.failures = data.get("failures", {})
        except:
            pass

    def _save(self):
        try:
            with open(MEMORY_FILE, 'w') as f:
                json.dump({
                    "successes": self.successes,
                    "failures": self.failures
                }, f, indent=2)
        except:
            pass

    def remember_success(self, task_type: str, approach: Dict):
        self.successes[task_type] = approach
        self._save()

    def remember_failure(self, task_type: str, approach: Dict, reason: str):
        if task_type not in self.failures:
            self.failures[task_type] = []
        self.failures[task_type].append({"approach": approach, "reason": reason})
        self._save()

    def get_context(self, task_type: str) -> Dict:
        return {
            "worked_before": self.successes.get(task_type),
            "failed_before": self.failures.get(task_type, [])[-3:]  # Last 3 failures
        }


# =============================================================================
# REASONER - Claude figures out HOW
# =============================================================================

class Reasoner:
    """Uses Claude to figure out how to accomplish any task"""

    def __init__(self, claude_client, tools: ToolRegistry, memory: Memory):
        self.claude = claude_client
        self.tools = tools
        self.memory = memory

    def plan(self, request: str, context: Dict) -> Dict:
        """Ask Claude to create a plan for the task"""

        memory_context = self.memory.get_context(self._task_type(request))

        prompt = f"""You are an intelligent Mac assistant. Figure out how to accomplish this task.

USER REQUEST: {request}

AVAILABLE TOOLS:
{self.tools.list_tools()}

SYSTEM CONTEXT:
- User: {context.get('user', 'unknown')}
- Running apps: {context.get('running_apps', [])}

MEMORY (what worked/failed before for similar tasks):
{json.dumps(memory_context, indent=2) if memory_context.get('worked_before') or memory_context.get('failed_before') else 'No previous attempts.'}

Think step by step:
1. What does the user actually want to accomplish?
2. What information do I need to gather first?
3. What sequence of tools will achieve this?
4. How do I verify each step worked?
5. What should I try if something fails?

Return a JSON plan:
{{
    "goal": "what we're trying to achieve",
    "steps": [
        {{
            "tool": "tool_name",
            "params": {{"param1": "value1"}},
            "purpose": "why this step",
            "verify": "how to check it worked",
            "on_failure": "alternative approach or null"
        }}
    ],
    "final_verification": "how to confirm the overall goal was achieved"
}}

Return ONLY valid JSON, no other text:"""

        response = self.claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )

        result = response.content[0].text.strip()

        # Parse JSON, handling markdown code blocks
        if "```json" in result:
            result = result.split("```json")[1].split("```")[0]
        elif "```" in result:
            result = result.split("```")[1].split("```")[0]

        return json.loads(result)

    def _task_type(self, request: str) -> str:
        """Extract a general task type for memory lookup"""
        request_lower = request.lower()
        if any(x in request_lower for x in ['message', 'text', 'imessage', 'send']):
            return "send_message"
        if any(x in request_lower for x in ['open', 'launch']):
            return "open_app"
        if any(x in request_lower for x in ['play', 'music', 'spotify']):
            return "play_music"
        if any(x in request_lower for x in ['tweet', 'twitter', 'x.com']):
            return "twitter"
        return "general"


# =============================================================================
# EXECUTOR - Run the plan
# =============================================================================

class Executor:
    """Executes plans, threading outputs between steps"""

    def __init__(self, tools: ToolRegistry):
        self.tools = tools

    def run(self, plan: Dict) -> Dict:
        """Execute a plan step by step"""
        state = {
            "outputs": {},
            "failures": [],
            "steps_completed": []
        }

        for i, step in enumerate(plan.get("steps", [])):
            tool_name = step.get("tool")
            params = step.get("params", {})

            # Substitute variables from previous outputs
            params = self._substitute_vars(params, state["outputs"])

            # Get the tool
            tool = self.tools.get(tool_name)
            if not tool:
                state["failures"].append({
                    "step": i,
                    "tool": tool_name,
                    "error": f"Unknown tool: {tool_name}"
                })
                continue

            # Execute
            result = tool.execute(**params)

            # Verify
            if not tool.verify(result):
                state["failures"].append({
                    "step": i,
                    "tool": tool_name,
                    "result": result,
                    "on_failure": step.get("on_failure")
                })

                # Try alternative if specified
                if step.get("on_failure"):
                    # For now, just record that we should try alternative
                    pass
            else:
                state["steps_completed"].append({
                    "step": i,
                    "tool": tool_name,
                    "result": result
                })

            # Store output for next steps
            state["outputs"][f"step_{i}"] = result
            state["outputs"][tool_name] = result

        # Determine overall success
        state["success"] = len(state["failures"]) == 0
        state["goal"] = plan.get("goal")

        return state

    def _substitute_vars(self, params: Dict, outputs: Dict) -> Dict:
        """Replace variable references with actual values"""
        result = {}
        for key, value in params.items():
            if isinstance(value, str):
                # Replace ${step_N.output.field} patterns
                for var_name, var_value in outputs.items():
                    if isinstance(var_value, dict) and var_value.get("output"):
                        placeholder = f"${{{var_name}}}"
                        if placeholder in value:
                            value = str(var_value["output"])
                result[key] = value
            else:
                result[key] = value
        return result


# =============================================================================
# RECOVERY - Handle failures
# =============================================================================

class Recovery:
    """Reflects on failures and suggests alternatives"""

    def __init__(self, claude_client, tools: ToolRegistry):
        self.claude = claude_client
        self.tools = tools

    def reflect(self, failures: List[Dict], original_plan: Dict) -> Dict:
        """Analyze what went wrong and suggest fix"""

        if not failures:
            return {"action": "none"}

        prompt = f"""A task failed. Analyze what went wrong and suggest a fix.

ORIGINAL GOAL: {original_plan.get('goal')}

FAILURES:
{json.dumps(failures, indent=2, default=str)}

AVAILABLE TOOLS:
{self.tools.list_tools()}

Questions:
1. Why did each step fail?
2. Is there an alternative approach?
3. Do we need more information from the user?

Return JSON:
{{
    "analysis": "what went wrong",
    "action": "retry" | "ask_user" | "give_up",
    "new_plan": {{...}} if action is retry,
    "question": "..." if action is ask_user,
    "explanation": "..." if action is give_up
}}

Return ONLY valid JSON:"""

        response = self.claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}]
        )

        result = response.content[0].text.strip()

        if "```json" in result:
            result = result.split("```json")[1].split("```")[0]
        elif "```" in result:
            result = result.split("```")[1].split("```")[0]

        try:
            return json.loads(result)
        except:
            return {"action": "give_up", "explanation": "Could not analyze failure"}


# =============================================================================
# CLAWDBOT v9 - Main Agent (JARVIS Mode)
# =============================================================================

class ClawdBot:
    """The main intelligent agent"""

    def __init__(self):
        self.claude = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        self.tools = ToolRegistry()
        self.memory = Memory()
        self.reasoner = Reasoner(self.claude, self.tools, self.memory)
        self.executor = Executor(self.tools)
        self.recovery = Recovery(self.claude, self.tools)
        self.costs = 0.0

    def log(self, tag: str, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"{ts} [{tag:8}] {msg}")

    def get_context(self) -> Dict:
        """Gather current system context"""
        context = {
            "user": os.environ.get("USER"),
            "home": os.path.expanduser("~"),
        }

        # Get running apps
        try:
            result = self.tools.get("get_running_apps").execute()
            context["running_apps"] = result.get("output", {}).get("apps", [])
        except:
            context["running_apps"] = []

        return context

    def process(self, request: str) -> str:
        """Main entry point - process any request"""

        # Handle built-in commands
        text = request.lower().strip()
        if not text:
            return None
        if text in ['quit', 'exit', 'q']:
            return "EXIT"
        if text in ['help', '?']:
            return self.get_help()
        if text in ['costs', 'cost']:
            return f"Session cost: ${self.costs:.4f}"

        # 1. Get context
        self.log("CONTEXT", "Gathering system state...")
        context = self.get_context()

        # 2. Reason about the task
        self.log("THINKING", f"Planning: {request}")
        try:
            plan = self.reasoner.plan(request, context)
            self.log("PLAN", f"Goal: {plan.get('goal')}")
            for i, step in enumerate(plan.get("steps", [])):
                self.log("STEP", f"  {i+1}. {step.get('tool')}: {step.get('purpose')}")
        except Exception as e:
            self.log("ERROR", f"Planning failed: {e}")
            return f"✗ Could not figure out how to do that: {e}"

        # 3. Execute the plan
        self.log("EXECUTE", "Running plan...")
        result = self.executor.run(plan)

        # 4. Handle failures with recovery
        retry_count = 0
        while not result["success"] and retry_count < MAX_RETRIES:
            self.log("FAILURE", f"Step failed, reflecting... (attempt {retry_count + 1})")
            recovery = self.recovery.reflect(result["failures"], plan)

            if recovery.get("action") == "retry" and recovery.get("new_plan"):
                self.log("RETRY", "Trying alternative approach...")
                result = self.executor.run(recovery["new_plan"])
            elif recovery.get("action") == "ask_user":
                return f"❓ {recovery.get('question', 'Need more information')}"
            else:
                break

            retry_count += 1

        # 5. Remember what happened
        task_type = self.reasoner._task_type(request)
        if result["success"]:
            self.memory.remember_success(task_type, plan)
        else:
            self.memory.remember_failure(task_type, plan, str(result.get("failures")))

        # 6. Format response
        return self.format_response(result, plan)

    def format_response(self, result: Dict, plan: Dict) -> str:
        """Create a human-readable response"""
        lines = []

        if result["success"]:
            lines.append(f"✓ {plan.get('goal', 'Done')}")

            # Add details from completed steps
            for step in result.get("steps_completed", []):
                output = step.get("result", {}).get("output", {})
                if isinstance(output, dict):
                    # Show apps list
                    if output.get("apps"):
                        lines.append(f"\nRunning apps: {', '.join(output['apps'][:15])}")
                    # Show query results
                    elif output.get("rows"):
                        lines.append(f"\nResults: {output['rows'][:10]}")
                    # Show file content (truncated)
                    elif output.get("content"):
                        content = output["content"][:500]
                        lines.append(f"\n{content}")
                    # Show stdout from bash
                    elif output.get("stdout"):
                        lines.append(f"\n{output['stdout'][:500]}")
                    # Show verification
                    elif output.get("verified"):
                        lines.append(f"  ✓ Verified: {step['tool']}")
                    # Show sent message
                    elif output.get("sent"):
                        lines.append(f"  ✓ Sent to {output.get('recipient')}: \"{output.get('message')}\"")
                    # Show opened URL/app
                    elif output.get("opened"):
                        lines.append(f"  ✓ Opened: {output.get('url') or output.get('app')}")
        else:
            lines.append(f"✗ Could not complete: {plan.get('goal', 'task')}")

            for failure in result.get("failures", []):
                error = failure.get("result", {}).get("error") or failure.get("error")
                lines.append(f"  ✗ {failure.get('tool')}: {error}")

        return "\n".join(lines)

    def get_help(self) -> str:
        browser_status = "✓ Browser automation enabled" if BROWSER_AVAILABLE else "✗ Browser not available"
        return f"""ClawdBot v{VERSION} - JARVIS Mode

{browser_status}

Just tell me what you want in plain English. I'll figure it out AND do it.

BROWSER TASKS (new in v9!):
  "follow 5 people on instagram"
  "like some posts on twitter"
  "search youtube for lofi and play the first video"
  "post a tweet saying hello world"

LOCAL TASKS:
  "send hi to halit on imessage"
  "what apps are running?"
  "create a file called notes.txt"
  "open spotify"

I'll:
- Figure out the steps needed
- Navigate, click, type in browser
- Execute them with real tools
- Verify they actually worked
- Tell you honestly if something failed

Type 'quit' to exit, 'costs' to see API usage.
"""


# =============================================================================
# MAIN
# =============================================================================

def main():
    print(f"""
╔═══════════════════════════════════════════════════════════╗
║  ClawdBot v{VERSION} - JARVIS Mode                              ║
║  Browser automation + Reasoning = Does ANYTHING           ║
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
                print(f"\n👋 Goodbye! Session cost: ${bot.costs:.4f}")
                break

            if result:
                print(f"\n🤖 ClawdBot:\n{result}")

        except KeyboardInterrupt:
            print(f"\n\n👋 Goodbye! Session cost: ${bot.costs:.4f}")
            break
        except EOFError:
            break


if __name__ == "__main__":
    main()
