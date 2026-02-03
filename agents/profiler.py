#!/usr/bin/env python3
"""
Profiler Agent - Learns everything about the user
Strategy: GLM-4.7 (FREE) for 90% of work, Claude Sonnet for final synthesis
"""

import os
import json
import time
from pathlib import Path


class ProfilerAgent:
    def __init__(self, bot):
        self.bot = bot  # ClawdBot instance
        self.profile_path = os.path.expanduser("~/.clawdbot_user_profile.md")
        self.gathered_data = {}

    def log(self, msg):
        print(f"  [PROFILER] {msg}")

    # =========================================================================
    # DATA GATHERING (GLM - FREE)
    # =========================================================================

    def _glm_analyze(self, prompt, max_retries=3):
        """Use GLM-4.7 for analysis - FREE, unlimited retries"""
        for attempt in range(max_retries):
            try:
                response = self.bot.glm.chat.completions.create(
                    model="glm-4-flash",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=1500
                )
                return response.choices[0].message.content
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                return f"Analysis failed: {e}"
        return "Analysis failed after retries"

    def _list_files(self, directory, max_depth=2, max_files=50):
        """List files in directory"""
        try:
            result = []
            directory = os.path.expanduser(directory)
            for root, dirs, files in os.walk(directory):
                # Skip hidden and virtual env directories
                dirs[:] = [d for d in dirs if not d.startswith('.') and d != 'venv' and d != 'node_modules' and d != '__pycache__']

                depth = root.replace(directory, '').count(os.sep)
                if depth < max_depth:
                    for file in files[:20]:
                        if not file.startswith('.'):
                            rel_path = os.path.relpath(os.path.join(root, file), directory)
                            result.append(rel_path)
                            if len(result) >= max_files:
                                return "\n".join(result)
            return "\n".join(result)
        except Exception as e:
            return f"Error listing {directory}: {e}"

    def _read_file_safe(self, path, max_chars=4000):
        """Safely read file content"""
        try:
            path = os.path.expanduser(path)
            if os.path.exists(path):
                with open(path, 'r', errors='ignore') as f:
                    content = f.read()
                return content[:max_chars]
        except:
            pass
        return None

    def gather_project_info(self):
        """Scan project directories with GLM analysis"""
        self.log("Scanning project directories...")

        projects = {}
        dirs_to_scan = [
            ("~/clawdbot-v2", "ClawdBot - Multi-agent Mac assistant"),
            ("~/superquant", "SuperQuant - Trading bot"),
            ("~/Desktop", "Desktop files"),
            ("~/Documents", "Documents"),
        ]

        for dir_path, description in dirs_to_scan:
            expanded = os.path.expanduser(dir_path)
            if os.path.exists(expanded):
                files = self._list_files(dir_path)
                if files and len(files) > 10:
                    self.log(f"  Analyzing {dir_path}...")
                    analysis = self._glm_analyze(f"""Analyze this file listing from "{description}" ({dir_path}).
What does this tell us about the user's projects, skills, and interests?

Files:
{files}

Respond with 3-5 bullet points of insights.""")
                    projects[dir_path] = {
                        "description": description,
                        "analysis": analysis
                    }

        self.gathered_data["projects"] = projects
        return projects

    def gather_code_insights(self):
        """Analyze key code files with GLM"""
        self.log("Analyzing code files...")

        code_insights = {}
        key_files = [
            ("~/clawdbot-v2/clawdbot.py", "Main ClawdBot code"),
            ("~/clawdbot-v2/README.md", "ClawdBot documentation"),
            ("~/clawdbot-v2/dashboard.py", "ClawdBot dashboard"),
        ]

        for file_path, description in key_files:
            content = self._read_file_safe(file_path, max_chars=3000)
            if content:
                self.log(f"  Analyzing {file_path}...")
                analysis = self._glm_analyze(f"""Analyze this code/doc from "{description}".
What does it reveal about:
1. The user's technical skills
2. Their coding style
3. What they're building
4. Their priorities

Content:
{content}

Respond with bullet points.""")
                code_insights[file_path] = analysis

        self.gathered_data["code"] = code_insights
        return code_insights

    def gather_memory_data(self):
        """Analyze ClawdBot memory for usage patterns"""
        self.log("Analyzing memory and history...")

        memory_path = os.path.expanduser("~/.clawdbot_memory.json")
        if os.path.exists(memory_path):
            content = self._read_file_safe(memory_path)
            if content:
                analysis = self._glm_analyze(f"""Analyze this ClawdBot memory/history.
What patterns do you see about how the user interacts?
What do they ask for most? What are their preferences?

Memory:
{content}

Respond with insights about user behavior and preferences.""")
                self.gathered_data["memory"] = analysis
                return analysis

        self.gathered_data["memory"] = "No memory file found"
        return None

    def gather_all_data(self):
        """Run all data gathering (GLM only - FREE)"""
        self.log("Starting data gathering (GLM - free)...")

        self.gather_project_info()
        self.gather_code_insights()
        self.gather_memory_data()

        self.log(f"Gathered data from {len(self.gathered_data)} sources")
        return self.gathered_data

    # =========================================================================
    # PROFILE SYNTHESIS (Claude Sonnet - ONE CALL)
    # =========================================================================

    def synthesize_profile(self):
        """Use Claude Sonnet ONCE to create final profile"""
        self.log("Synthesizing profile (Claude Sonnet - single call)...")

        # Compile all gathered data
        compiled = []

        if "projects" in self.gathered_data:
            compiled.append("=== PROJECT ANALYSIS ===")
            for path, data in self.gathered_data["projects"].items():
                compiled.append(f"\n{path} ({data['description']}):\n{data['analysis']}")

        if "code" in self.gathered_data:
            compiled.append("\n=== CODE ANALYSIS ===")
            for path, analysis in self.gathered_data["code"].items():
                compiled.append(f"\n{path}:\n{analysis}")

        if "memory" in self.gathered_data:
            compiled.append(f"\n=== USAGE PATTERNS ===\n{self.gathered_data['memory']}")

        all_data = "\n".join(compiled)

        prompt = f"""Create a comprehensive USER PROFILE based on this analyzed data.

GATHERED DATA:
{all_data}

KNOWN FACTS (from direct conversation):
- Name: Shamil
- Location: Sandy, Utah
- Job: Amazon warehouse, 6pm-3am night shifts
- Life: Getting married soon
- Main Projects: ClawdBot (multi-agent Mac assistant), SuperQuant (XRP/SOL trading bot)
- Revenue Goals: Polymarket referrals ($0.01/click + $10/deposit), Dubco subscriptions
- API Budget: Unlimited GLM-4.7, limited Claude (use sparingly)
- Work Style: Wants ELITE quality, ships fast, iterates, no patience for broken tools
- Tech: Python, APIs, automation, AI/ML, macOS Sequoia

CREATE THIS EXACT STRUCTURE:

# USER PROFILE: Shamil

## IDENTITY
- Full context on who this person is

## CURRENT SITUATION
- Job schedule and constraints
- Life circumstances
- Available time for projects

## GOALS (Priority Order)
1. Financial independence through automated income
2. [Continue with specific goals...]

## ACTIVE PROJECTS

### ClawdBot
- Status: [what's built]
- Features: [key capabilities]
- Next: [what to build next]

### SuperQuant
- Status: [current state]
- Strategy: [trading approach]
- Challenges: [blockers]

### Revenue Streams
- Polymarket: [strategy]
- Dubco: [strategy]
- Other: [opportunities]

## TECHNICAL SKILLS
- Strong: [list]
- Learning: [list]
- Tools: [list]

## WORK STYLE
- [How they prefer to work]
- [Communication preferences]
- [Quality expectations]

## CONSTRAINTS
- Time: [specifics]
- Budget: [API costs, etc]
- Energy: [night shift impact]

## AGENT INSTRUCTIONS
When building agents for this user:
1. [Specific instruction]
2. [Specific instruction]
3. [Continue...]

Make this profile ACTIONABLE - every section should help future agents understand exactly how to serve this user effectively."""

        try:
            response = self.bot.claude.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt}]
            )
            profile = response.content[0].text

            # Track cost
            cost = (response.usage.input_tokens * 3 + response.usage.output_tokens * 15) / 1_000_000
            self.log(f"Claude Sonnet cost: ${cost:.4f}")

            return profile

        except Exception as e:
            self.log(f"Claude failed: {e}")
            return None

    # =========================================================================
    # MAIN METHODS
    # =========================================================================

    def build_profile(self):
        """Main method - builds complete user profile"""
        print("\n🧠 Building User Profile...")
        print("=" * 50)

        # Step 1: Gather data with GLM (FREE)
        self.gather_all_data()

        # Step 2: Synthesize with Claude Sonnet (ONE CALL)
        profile = self.synthesize_profile()

        if profile:
            # Save profile
            with open(self.profile_path, 'w') as f:
                f.write(profile)

            print("=" * 50)
            print(f"✅ Profile saved to {self.profile_path}")
            print(f"   Size: {len(profile)} characters")

            return profile
        else:
            print("❌ Failed to build profile")
            return None

    def get_profile(self):
        """Load existing profile"""
        if os.path.exists(self.profile_path):
            with open(self.profile_path, 'r') as f:
                return f.read()
        return None

    def get_profile_summary(self, max_chars=1500):
        """Get condensed profile for prompts"""
        profile = self.get_profile()
        if profile:
            return profile[:max_chars]
        return "No user profile available."

    def update_profile(self, new_info):
        """Update profile with new information (GLM - FREE)"""
        current = self.get_profile() or ""

        updated = self._glm_analyze(f"""Update this user profile with new information.
Keep the same structure, integrate the new info appropriately.

CURRENT PROFILE:
{current[:3000]}

NEW INFORMATION:
{new_info}

Output the complete updated profile.""")

        if updated and len(updated) > 500:
            with open(self.profile_path, 'w') as f:
                f.write(updated)
            self.log("Profile updated")
            return updated

        return current


# Quick test
if __name__ == "__main__":
    print("Profiler Agent - Run via: python clawdbot.py --profile")
