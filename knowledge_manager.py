#!/usr/bin/env python3
"""
KnowledgeManager - Persistent System Knowledge for ClawdBot
===========================================================
Loads, queries, updates, and saves knowledge about YOUR specific setup.

Knowledge File: ~/.clawdbot/system_knowledge.json

Features:
- Site-specific workflows (how to do things on Instagram, Twitter, etc.)
- Contact info (Instagram usernames, iMessage numbers, emails)
- Learned failures (what NOT to do)
- Confidence scores (how reliable is this knowledge?)
- Auto-learning from successes and failures
"""

import os
import json
from datetime import datetime
from typing import Dict, List, Optional, Any


class KnowledgeManager:
    """
    Load, query, update, and save system knowledge.

    This is the brain that makes ClawdBot smarter over time.
    """

    KNOWLEDGE_DIR = os.path.expanduser("~/.clawdbot")
    KNOWLEDGE_PATH = os.path.expanduser("~/.clawdbot/system_knowledge.json")

    def __init__(self):
        self.knowledge = self._load()
        self._dirty = False  # Track if we need to save

    # =========================================================================
    # LOADING & SAVING
    # =========================================================================

    def _load(self) -> Dict:
        """Load knowledge from file, create default if missing"""
        # Ensure directory exists
        os.makedirs(self.KNOWLEDGE_DIR, exist_ok=True)

        if os.path.exists(self.KNOWLEDGE_PATH):
            try:
                with open(self.KNOWLEDGE_PATH, 'r') as f:
                    data = json.load(f)
                    print(f"✓ Loaded knowledge from {self.KNOWLEDGE_PATH}")
                    return data
            except Exception as e:
                print(f"⚠ Error loading knowledge: {e}, using defaults")
                return self._get_default_knowledge()
        else:
            print(f"⚠ No knowledge file found, creating default at {self.KNOWLEDGE_PATH}")
            default = self._get_default_knowledge()
            self._save_knowledge(default)
            return default

    def _get_default_knowledge(self) -> Dict:
        """Return default knowledge structure"""
        return {
            "version": "1.0",
            "last_updated": datetime.now().isoformat(),
            "created_at": datetime.now().isoformat(),
            "browser": {
                "app": "Comet",
                "path": "/Applications/Comet.app",
                "debug_port": 9222
            },
            "sites": {},
            "contacts": {},
            "learned_failures": [],
            "apps": {}
        }

    def save(self):
        """Persist knowledge to file if dirty"""
        if self._dirty:
            self._save_knowledge(self.knowledge)
            self._dirty = False

    def _save_knowledge(self, data: Dict):
        """Actually write to file"""
        data["last_updated"] = datetime.now().isoformat()
        try:
            with open(self.KNOWLEDGE_PATH, 'w') as f:
                json.dump(data, f, indent=2)
            print(f"✓ Saved knowledge to {self.KNOWLEDGE_PATH}")
        except Exception as e:
            print(f"✗ Error saving knowledge: {e}")

    def force_save(self):
        """Force save regardless of dirty flag"""
        self._save_knowledge(self.knowledge)
        self._dirty = False

    # =========================================================================
    # SITE WORKFLOWS
    # =========================================================================

    def get_site_workflow(self, site: str, task: str) -> Optional[Dict]:
        """
        Get step-by-step workflow for a task on a site.

        Args:
            site: Domain like "instagram.com" or "twitter.com"
            task: Task name like "send_dm", "follow_user", "search"

        Returns:
            Dict with 'steps' list and metadata, or None if not found
        """
        sites = self.knowledge.get("sites", {})

        # Normalize site (remove www.)
        site = site.replace("www.", "")

        # Check direct match
        if site in sites:
            workflows = sites[site].get("workflows", {})
            if task in workflows:
                return workflows[task]

        # Check alt_domains (e.g., x.com -> twitter.com)
        for site_key, site_data in sites.items():
            alt_domains = site_data.get("alt_domains", [])
            if site in alt_domains:
                workflows = site_data.get("workflows", {})
                if task in workflows:
                    return workflows[task]

        return None

    def get_site_info(self, site: str) -> Optional[Dict]:
        """Get all info about a site"""
        site = site.replace("www.", "")
        sites = self.knowledge.get("sites", {})

        if site in sites:
            return sites[site]

        # Check alt_domains
        for site_key, site_data in sites.items():
            if site in site_data.get("alt_domains", []):
                return site_data

        return None

    def extract_site_from_url(self, url: str) -> str:
        """Extract domain from URL"""
        if not url:
            return ""
        # Remove protocol
        url = url.replace("https://", "").replace("http://", "")
        # Get domain
        domain = url.split("/")[0]
        # Remove www
        domain = domain.replace("www.", "")
        return domain

    def extract_task_from_goal(self, goal: str) -> str:
        """Infer task type from goal text"""
        goal_lower = goal.lower()

        # DM detection
        if any(kw in goal_lower for kw in ["dm", "message", "send", "text"]):
            if any(kw in goal_lower for kw in ["instagram", "twitter", "x.com", "on ig"]):
                return "send_dm"

        # Follow detection
        if "follow" in goal_lower:
            return "follow_user"

        # Search detection
        if "search" in goal_lower:
            return "search"

        # Like detection
        if "like" in goal_lower:
            return "like_post"

        return "unknown"

    def extract_site_from_goal(self, goal: str) -> str:
        """Infer site from goal text"""
        goal_lower = goal.lower()

        if any(kw in goal_lower for kw in ["instagram", "insta", "ig"]):
            return "instagram.com"
        if any(kw in goal_lower for kw in ["twitter", "x.com", "tweet"]):
            return "twitter.com"
        if "youtube" in goal_lower:
            return "youtube.com"
        if "facebook" in goal_lower:
            return "facebook.com"
        if "google" in goal_lower:
            return "google.com"

        return ""

    # =========================================================================
    # CONTACTS
    # =========================================================================

    def get_contact(self, name: str) -> Optional[Dict]:
        """Get contact info by name (case-insensitive)"""
        contacts = self.knowledge.get("contacts", {})
        name_lower = name.lower()

        for contact_name, contact_info in contacts.items():
            if contact_name.lower() == name_lower:
                return {"name": contact_name, **contact_info}

        return None

    def update_contact(self, name: str, platform: str, value: str):
        """Update or create contact info"""
        contacts = self.knowledge.setdefault("contacts", {})
        name_lower = name.lower()

        # Find existing or create new
        existing_key = None
        for key in contacts:
            if key.lower() == name_lower:
                existing_key = key
                break

        if existing_key:
            contacts[existing_key][platform] = value
        else:
            contacts[name_lower] = {platform: value}

        self._dirty = True

    # =========================================================================
    # FAILURE LEARNING
    # =========================================================================

    def get_failures_for_site(self, site: str) -> List[Dict]:
        """Get all learned failures for a site"""
        site = site.replace("www.", "")
        failures = self.knowledge.get("learned_failures", [])
        return [f for f in failures if f.get("site") == site]

    def get_failures_for_task(self, site: str, task: str) -> List[Dict]:
        """Get failures specific to a task on a site"""
        site = site.replace("www.", "")
        failures = self.knowledge.get("learned_failures", [])
        return [f for f in failures if f.get("site") == site and f.get("task") == task]

    def record_failure(self, site: str, task: str, wrong_approach: str,
                       why_failed: str = "", correct_approach: str = ""):
        """
        Record a failed approach so we don't repeat it.

        Args:
            site: Domain where failure occurred
            task: Task that failed
            wrong_approach: What was tried that didn't work
            why_failed: Why it didn't work (optional)
            correct_approach: What should be done instead (optional)
        """
        site = site.replace("www.", "")

        failures = self.knowledge.setdefault("learned_failures", [])

        # Check if we already know about this failure
        for f in failures:
            if (f.get("site") == site and
                f.get("task") == task and
                f.get("wrong_approach") == wrong_approach):
                # Already recorded, update confidence
                f["confidence"] = min(1.0, f.get("confidence", 0.5) + 0.1)
                f["last_seen"] = datetime.now().isoformat()
                self._dirty = True
                return

        # New failure
        failures.append({
            "site": site,
            "task": task,
            "wrong_approach": wrong_approach,
            "why_failed": why_failed,
            "correct_approach": correct_approach,
            "learned_at": datetime.now().isoformat(),
            "confidence": 0.8
        })

        self._dirty = True
        print(f"📚 Learned: Don't {wrong_approach} on {site}")

    # =========================================================================
    # SUCCESS LEARNING
    # =========================================================================

    def record_success(self, site: str, task: str, steps: List[Dict]):
        """
        Record a successful task completion.
        Updates confidence scores and optionally learns new workflows.

        Args:
            site: Domain where success occurred
            task: Task that succeeded
            steps: List of steps that were taken
        """
        site = site.replace("www.", "")

        sites = self.knowledge.setdefault("sites", {})
        site_data = sites.setdefault(site, {"workflows": {}})
        workflows = site_data.setdefault("workflows", {})

        if task in workflows:
            # Existing workflow - increase confidence
            workflow = workflows[task]
            workflow["confidence"] = min(1.0, workflow.get("confidence", 0.5) + 0.05)
            workflow["success_count"] = workflow.get("success_count", 0) + 1
            workflow["last_success"] = datetime.now().isoformat()
        else:
            # New workflow learned from success!
            workflows[task] = {
                "confidence": 0.7,  # Start with decent confidence
                "learned_from": "success",
                "success_count": 1,
                "fail_count": 0,
                "last_success": datetime.now().isoformat(),
                "steps": steps
            }
            print(f"📚 Learned new workflow: {task} on {site}")

        self._dirty = True

    def record_workflow_failure(self, site: str, task: str):
        """Record that a workflow failed (decrease confidence)"""
        site = site.replace("www.", "")

        sites = self.knowledge.get("sites", {})
        if site in sites:
            workflows = sites[site].get("workflows", {})
            if task in workflows:
                workflow = workflows[task]
                workflow["confidence"] = max(0.1, workflow.get("confidence", 0.5) - 0.1)
                workflow["fail_count"] = workflow.get("fail_count", 0) + 1
                self._dirty = True

    # =========================================================================
    # PROMPT GENERATION
    # =========================================================================

    def get_prompt_knowledge(self, site: str = None, task: str = None) -> str:
        """
        Format knowledge for Claude's prompt.

        Args:
            site: Optional site to focus on
            task: Optional task to focus on

        Returns:
            Formatted string to include in Claude's prompt
        """
        lines = []
        lines.append("═" * 79)
        lines.append("SYSTEM KNOWLEDGE (learned from your computer):")
        lines.append("═" * 79)

        # Site-specific workflow
        if site and task:
            workflow = self.get_site_workflow(site, task)
            if workflow:
                lines.append(f"\n✓ KNOWN WORKFLOW for {task} on {site}:")
                lines.append(f"  Confidence: {workflow.get('confidence', 0):.0%}")
                steps = workflow.get("steps", [])
                for i, step in enumerate(steps, 1):
                    action = step.get("action", "?")
                    note = step.get("note", "")
                    if action == "click":
                        target = step.get("target", "?")
                        lines.append(f"  {i}. CLICK: {target} ({note})")
                    elif action == "type":
                        field = step.get("field", "")
                        lines.append(f"  {i}. TYPE in '{field}' ({note})")
                    elif action == "wait":
                        secs = step.get("seconds", 2)
                        lines.append(f"  {i}. WAIT {secs} seconds ({note})")
                    elif action == "press":
                        key = step.get("key", "?")
                        lines.append(f"  {i}. PRESS {key} ({note})")
                    elif action == "navigate":
                        url = step.get("url", "?")
                        lines.append(f"  {i}. GO TO: {url}")
                    else:
                        lines.append(f"  {i}. {action.upper()}: {step}")

        # Failures to avoid
        if site:
            failures = self.get_failures_for_site(site)
            if failures:
                lines.append(f"\n⚠️ KNOWN FAILURES TO AVOID on {site}:")
                for f in failures:
                    wrong = f.get("wrong_approach", "?")
                    correct = f.get("correct_approach", "")
                    lines.append(f"  ✗ DON'T: {wrong}")
                    if correct:
                        lines.append(f"    ✓ INSTEAD: {correct}")

        # Browser info
        browser = self.knowledge.get("browser", {})
        if browser:
            app = browser.get("app", "Chrome")
            lines.append(f"\n🌐 Browser: {app} (has saved logins)")

        lines.append("═" * 79)

        return "\n".join(lines)

    def get_all_failures_prompt(self) -> str:
        """Get all failures formatted for prompt"""
        failures = self.knowledge.get("learned_failures", [])
        if not failures:
            return ""

        lines = ["LEARNED FAILURES (never repeat these):"]
        for f in failures:
            site = f.get("site", "?")
            wrong = f.get("wrong_approach", "?")
            lines.append(f"  • {site}: Don't {wrong}")

        return "\n".join(lines)

    # =========================================================================
    # USER INTERACTION
    # =========================================================================

    def ask_and_learn(self, task: str, site: str = "") -> str:
        """
        Ask user how to do something, save their answer.

        This is called when ClawdBot is stuck and needs help.

        Args:
            task: What we're trying to do
            site: Where (optional)

        Returns:
            User's instructions
        """
        print(f"\n❓ I'm stuck on: {task}")
        if site:
            print(f"   Site: {site}")
        print("   How should I do this? (describe the steps)")

        try:
            user_input = input("   Your answer: ").strip()

            if user_input:
                # Save as a learned instruction
                self._save_user_instruction(task, site, user_input)
                return user_input

        except (EOFError, KeyboardInterrupt):
            pass

        return ""

    def _save_user_instruction(self, task: str, site: str, instruction: str):
        """Save user's instruction for future reference"""
        # For now, just record as a success hint
        if site:
            sites = self.knowledge.setdefault("sites", {})
            site_data = sites.setdefault(site, {"workflows": {}})
            site_data.setdefault("user_hints", []).append({
                "task": task,
                "instruction": instruction,
                "learned_at": datetime.now().isoformat()
            })
            self._dirty = True
            print(f"📚 Saved your instruction for {task} on {site}")

    # =========================================================================
    # DEBUG / INFO
    # =========================================================================

    def print_summary(self):
        """Print a summary of what we know"""
        print("\n📚 Knowledge Summary:")

        sites = self.knowledge.get("sites", {})
        print(f"  Sites: {len(sites)}")
        for site, data in sites.items():
            workflows = data.get("workflows", {})
            logged_in = "✓" if data.get("logged_in") else "✗"
            print(f"    {logged_in} {site}: {len(workflows)} workflows")

        contacts = self.knowledge.get("contacts", {})
        print(f"  Contacts: {len(contacts)}")

        failures = self.knowledge.get("learned_failures", [])
        print(f"  Learned failures: {len(failures)}")

        print(f"  Knowledge file: {self.KNOWLEDGE_PATH}")


# =============================================================================
# Standalone test
# =============================================================================

if __name__ == "__main__":
    km = KnowledgeManager()
    km.print_summary()

    print("\n--- Testing workflow lookup ---")
    workflow = km.get_site_workflow("instagram.com", "send_dm")
    if workflow:
        print(f"Found workflow with {len(workflow.get('steps', []))} steps")
        print(f"Confidence: {workflow.get('confidence', 0):.0%}")

    print("\n--- Testing prompt generation ---")
    prompt = km.get_prompt_knowledge("instagram.com", "send_dm")
    print(prompt[:500] + "..." if len(prompt) > 500 else prompt)
