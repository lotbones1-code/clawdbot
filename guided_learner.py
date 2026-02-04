#!/usr/bin/env python3
"""
GuidedLearner - Learn Workflows by Asking User Step-by-Step
============================================================
Instead of guessing how to do things, LEARN by doing with user guidance.

How it works:
1. User asks to do something (e.g., "send dm on instagram")
2. ClawdBot doesn't know how → enters learning mode
3. Takes screenshot, asks user "What should I click?"
4. User says "Click the Messages icon"
5. ClawdBot does it, records the step
6. Repeats until task complete
7. Saves the complete workflow as an agent

Next time: ClawdBot knows exactly how to do it.
"""

import os
import json
import base64
from datetime import datetime
from typing import Dict, List, Optional, Any

# Import browser control
try:
    from browser_cdp import BrowserCDP
    CDP_AVAILABLE = True
except ImportError:
    CDP_AVAILABLE = False


class GuidedLearner:
    """
    Learn workflows through interactive step-by-step guidance.

    This is how ClawdBot gets smarter - by ASKING instead of guessing.
    """

    AGENTS_DIR = os.path.expanduser("~/.clawdbot/agents")

    def __init__(self, browser: BrowserCDP = None):
        self.browser = browser or (BrowserCDP() if CDP_AVAILABLE else None)
        os.makedirs(self.AGENTS_DIR, exist_ok=True)

    # =========================================================================
    # AGENT MANAGEMENT
    # =========================================================================

    def list_agents(self) -> List[str]:
        """List all learned agents"""
        agents = []
        for f in os.listdir(self.AGENTS_DIR):
            if f.endswith(".json"):
                agents.append(f.replace(".json", ""))
        return agents

    def load_agent(self, name: str) -> Optional[Dict]:
        """Load a learned agent by name"""
        path = os.path.join(self.AGENTS_DIR, f"{name}.json")
        if os.path.exists(path):
            with open(path, 'r') as f:
                return json.load(f)
        return None

    def save_agent(self, name: str, agent: Dict):
        """Save a learned agent"""
        path = os.path.join(self.AGENTS_DIR, f"{name}.json")
        with open(path, 'w') as f:
            json.dump(agent, f, indent=2)
        print(f"✓ Saved agent to {path}")

    def find_agent_for_task(self, task: str, site: str) -> Optional[Dict]:
        """Find an agent that can handle this task"""
        # Try exact match first
        exact_name = f"{site.replace('.', '_')}_{task}"
        agent = self.load_agent(exact_name)
        if agent:
            return agent

        # Try task only
        agent = self.load_agent(task)
        if agent:
            return agent

        # Search all agents
        for agent_name in self.list_agents():
            agent = self.load_agent(agent_name)
            if agent and agent.get("task") == task:
                if site and agent.get("site") == site:
                    return agent
                elif not site:
                    return agent

        return None

    # =========================================================================
    # INTERACTIVE LEARNING
    # =========================================================================

    def learn_task(self, task_name: str, site: str, start_url: str = None) -> Optional[Dict]:
        """
        Learn a workflow interactively.

        1. Navigate to site
        2. Take screenshot
        3. Ask user what to do
        4. Do it
        5. Record step
        6. Repeat until user says "done"
        7. Save as agent

        Returns the learned agent, or None if cancelled.
        """
        if not self.browser:
            print("✗ Browser not available")
            return None

        print(f"\n{'='*60}")
        print(f"🎓 LEARNING MODE: {task_name}")
        print(f"{'='*60}")
        print("I'll learn by watching you guide me step by step.")
        print("At each step, tell me what to click/type/do.")
        print("Type 'done' when the task is complete.")
        print("Type 'cancel' to abort learning.")
        print(f"{'='*60}\n")

        steps = []
        step_num = 0

        # Navigate to start URL if provided
        if start_url:
            print(f"📍 Going to {start_url}...")
            if not self.browser.connect():
                print("✗ Could not connect to browser")
                return None
            self.browser.navigate(start_url)
            import time
            time.sleep(2)

            steps.append({
                "action": "navigate",
                "url": start_url,
                "note": "Starting point"
            })
            step_num += 1

        # Connect if not already
        if not self.browser.connect(site if site else None):
            print("✗ Could not connect to browser")
            return None

        # Learning loop
        while True:
            step_num += 1

            # Take screenshot
            print(f"\n--- Step {step_num} ---")
            screenshot_data = self.browser.screenshot_base64()

            current_url = screenshot_data.get("url", "")
            page_title = screenshot_data.get("title", "")

            print(f"📸 Current page: {page_title}")
            print(f"   URL: {current_url}")

            # Save screenshot for reference
            screenshot_path = f"/tmp/clawdbot_learn_step_{step_num}.png"
            if screenshot_data.get("image"):
                img_bytes = base64.b64decode(screenshot_data["image"])
                with open(screenshot_path, 'wb') as f:
                    f.write(img_bytes)
                print(f"   Screenshot saved: {screenshot_path}")

            # Ask user what to do
            print("\n❓ What should I do next?")
            print("   (e.g., 'click Messages', 'type hello in message field', 'press Enter')")
            print("   (or 'done' to finish, 'cancel' to abort)")

            try:
                user_input = input("\n   Your instruction: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n\n⚠ Learning cancelled.")
                return None

            if not user_input:
                continue

            # Handle special commands
            if user_input.lower() == "done":
                print("\n✓ Learning complete!")
                break

            if user_input.lower() == "cancel":
                print("\n⚠ Learning cancelled.")
                return None

            if user_input.lower() == "back" or user_input.lower() == "undo":
                if steps:
                    steps.pop()
                    print("↩ Removed last step")
                continue

            # Parse and execute instruction
            step = self._parse_instruction(user_input)

            if step:
                # Execute the step
                success = self._execute_step(step)

                if success:
                    # Record with screenshot
                    step["screenshot_before"] = screenshot_data.get("image", "")[:100] + "..."  # Truncated
                    step["user_instruction"] = user_input
                    step["url_at_step"] = current_url
                    steps.append(step)
                    print(f"   ✓ Step recorded: {step['action']}")
                else:
                    print("   ✗ Step failed - try again or type 'cancel'")

                # Wait for page to update
                import time
                time.sleep(1)
            else:
                print("   ⚠ Could not understand instruction. Try again.")
                print("   Examples: 'click Send', 'type hello', 'press Enter', 'wait 2 seconds'")

        # Build agent
        agent = {
            "task": task_name,
            "site": site,
            "learned_at": datetime.now().isoformat(),
            "learned_from": "guided_user_interaction",
            "total_steps": len(steps),
            "steps": steps,
            "success_indicator": None,
            "common_failures": []
        }

        # Ask for success indicator
        print("\n❓ How do I know if this task succeeded?")
        print("   (e.g., 'Message sent appears', 'Profile page loads')")
        try:
            indicator = input("   Success indicator: ").strip()
            if indicator:
                agent["success_indicator"] = {
                    "type": "text_appears",
                    "text": indicator
                }
        except:
            pass

        # Generate agent name
        agent_name = f"{site.replace('.', '_')}_{task_name}" if site else task_name

        # Save
        self.save_agent(agent_name, agent)

        print(f"\n✓ Learned '{agent_name}' with {len(steps)} steps!")
        print(f"   Next time, I'll do this automatically.")

        return agent

    def _parse_instruction(self, instruction: str) -> Optional[Dict]:
        """
        Parse user's natural language instruction into an action.

        Supported:
        - "click X" → {"action": "click", "target": "X"}
        - "type X" → {"action": "type", "text": "X"}
        - "type X in Y" → {"action": "type", "text": "X", "field": "Y"}
        - "press Enter" → {"action": "press", "key": "Enter"}
        - "wait N seconds" → {"action": "wait", "seconds": N}
        - "scroll down" → {"action": "scroll", "direction": "down"}
        """
        instruction = instruction.strip()
        lower = instruction.lower()

        # Click
        if lower.startswith("click "):
            target = instruction[6:].strip().strip('"\'')
            return {"action": "click", "target": target}

        # Type with field
        if " in " in lower and (lower.startswith("type ") or lower.startswith("enter ")):
            parts = instruction.split(" in ", 1)
            text = parts[0].split(" ", 1)[1].strip().strip('"\'')
            field = parts[1].strip().strip('"\'')
            return {"action": "type", "text": text, "field": field}

        # Type
        if lower.startswith("type ") or lower.startswith("enter "):
            text = instruction.split(" ", 1)[1].strip().strip('"\'')
            return {"action": "type", "text": text}

        # Press key
        if lower.startswith("press "):
            key = instruction[6:].strip()
            return {"action": "press", "key": key}

        # Wait
        if lower.startswith("wait"):
            import re
            match = re.search(r'(\d+)', instruction)
            seconds = int(match.group(1)) if match else 2
            return {"action": "wait", "seconds": seconds}

        # Scroll
        if "scroll" in lower:
            direction = "down" if "down" in lower else "up"
            return {"action": "scroll", "direction": direction}

        # Navigate
        if lower.startswith("go to ") or lower.startswith("navigate to "):
            url = instruction.split(" to ", 1)[1].strip()
            if not url.startswith("http"):
                url = "https://" + url
            return {"action": "navigate", "url": url}

        return None

    def _execute_step(self, step: Dict) -> bool:
        """Execute a single step"""
        action = step.get("action")

        try:
            if action == "click":
                result = self.browser.click(step.get("target"))
                return result.get("success", False)

            elif action == "type":
                result = self.browser.type_text(step.get("text"), step.get("field"))
                return result.get("success", False)

            elif action == "press":
                result = self.browser.press_key(step.get("key"))
                return result.get("success", False)

            elif action == "wait":
                import time
                time.sleep(step.get("seconds", 2))
                return True

            elif action == "scroll":
                result = self.browser.scroll(step.get("direction", "down"))
                return result.get("success", False)

            elif action == "navigate":
                result = self.browser.navigate(step.get("url"))
                return result.get("success", False)

            else:
                print(f"   ⚠ Unknown action: {action}")
                return False

        except Exception as e:
            print(f"   ✗ Error: {e}")
            return False

    # =========================================================================
    # AGENT EXECUTION
    # =========================================================================

    def execute_agent(self, agent: Dict, params: Dict = None) -> Dict:
        """
        Execute a learned agent workflow.

        params: Variables to substitute (e.g., {"recipient": "john", "message": "hello"})
        """
        if not self.browser:
            return {"success": False, "error": "Browser not available"}

        params = params or {}

        task = agent.get("task", "unknown")
        site = agent.get("site", "")
        steps = agent.get("steps", [])

        print(f"\n🤖 Executing: {task}")
        print(f"   Site: {site}")
        print(f"   Steps: {len(steps)}")
        print(f"   Params: {params}")

        if not self.browser.connect(site if site else None):
            return {"success": False, "error": "Could not connect to browser"}

        executed_steps = []

        for i, step in enumerate(steps, 1):
            # Substitute variables in step
            step_copy = self._substitute_params(step, params)

            print(f"\n   Step {i}/{len(steps)}: {step_copy.get('action')} - {step_copy.get('target', step_copy.get('text', step_copy.get('url', '')))}")

            success = self._execute_step(step_copy)
            executed_steps.append({
                "step": i,
                "action": step_copy,
                "success": success
            })

            if not success:
                print(f"   ✗ Step failed!")
                return {
                    "success": False,
                    "error": f"Failed at step {i}: {step_copy.get('action')}",
                    "completed_steps": i - 1,
                    "total_steps": len(steps),
                    "history": executed_steps
                }

            # Wait between steps
            import time
            time.sleep(1)

        print(f"\n✓ Task complete! ({len(steps)} steps)")

        return {
            "success": True,
            "task": task,
            "completed_steps": len(steps),
            "history": executed_steps
        }

    def _substitute_params(self, step: Dict, params: Dict) -> Dict:
        """Substitute ${variable} placeholders in step"""
        step_copy = dict(step)

        for key, value in step_copy.items():
            if isinstance(value, str):
                for param_name, param_value in params.items():
                    value = value.replace(f"${{{param_name}}}", str(param_value))
                    value = value.replace(f"${param_name}", str(param_value))
                step_copy[key] = value

        return step_copy


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import sys

    learner = GuidedLearner()

    if len(sys.argv) > 1:
        cmd = sys.argv[1]

        if cmd == "learn" and len(sys.argv) > 2:
            task = sys.argv[2]
            site = sys.argv[3] if len(sys.argv) > 3 else ""
            url = sys.argv[4] if len(sys.argv) > 4 else None
            learner.learn_task(task, site, url)

        elif cmd == "list":
            agents = learner.list_agents()
            print(f"Learned agents ({len(agents)}):")
            for name in agents:
                agent = learner.load_agent(name)
                if agent:
                    print(f"  {name}: {agent.get('task')} on {agent.get('site')} ({agent.get('total_steps', 0)} steps)")

        elif cmd == "show" and len(sys.argv) > 2:
            name = sys.argv[2]
            agent = learner.load_agent(name)
            if agent:
                print(json.dumps(agent, indent=2))
            else:
                print(f"Agent '{name}' not found")

        elif cmd == "run" and len(sys.argv) > 2:
            name = sys.argv[2]
            agent = learner.load_agent(name)
            if agent:
                # Parse params from remaining args
                params = {}
                for arg in sys.argv[3:]:
                    if "=" in arg:
                        k, v = arg.split("=", 1)
                        params[k] = v
                learner.execute_agent(agent, params)
            else:
                print(f"Agent '{name}' not found")

        else:
            print("Usage:")
            print("  python guided_learner.py learn <task> [site] [start_url]")
            print("  python guided_learner.py list")
            print("  python guided_learner.py show <agent_name>")
            print("  python guided_learner.py run <agent_name> [key=value ...]")

    else:
        print("Usage:")
        print("  python guided_learner.py learn <task> [site] [start_url]")
        print("  python guided_learner.py list")
        print("  python guided_learner.py show <agent_name>")
        print("  python guided_learner.py run <agent_name> [key=value ...]")
