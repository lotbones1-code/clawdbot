# PROFILER AGENT BUILD PROMPT

Copy this to Claude App (which has the repo connected):

---

You are building the **PROFILER AGENT** for ClawdBot - the foundation that learns everything about me so all agents understand my context.

## MY CONTEXT
- Building elite multi-agent system (ClawdBot)
- **Unlimited GLM-4.7 budget**, limited Claude budget
- Want to make money: Polymarket referrals ($0.01/click + $10/deposit), Dubco subscriptions
- Building SuperQuant trading bot (XRP/SOL automated trading)
- Live in Sandy, Utah, work Amazon warehouse 6pm-3am
- Getting married soon, need profitable systems
- Want ELITE quality - no mediocre work
- Low patience for broken tools

## API STRATEGY (CRITICAL)
```
GLM-4.7 (FREE/UNLIMITED):
- All data gathering and file reading
- Initial analysis passes
- Bulk text processing
- Retry loops until correct
- 90% of the work

Claude Sonnet (USE SPARINGLY):
- Final synthesis of profile
- Quality verification
- Complex reasoning that GLM can't handle
- ~10% of work

Claude Opus 4.5 (RARE):
- Only for critical strategic insights
- When Sonnet output isn't good enough
- <1% of work, ask user first
```

## BUILD: agents/profiler.py

```python
#!/usr/bin/env python3
"""
Profiler Agent - Learns everything about the user
Uses GLM-4.7 for heavy lifting, Claude Sonnet for synthesis
"""

import os
import json
from pathlib import Path

class ProfilerAgent:
    def __init__(self, bot):
        self.bot = bot  # ClawdBot instance with glm and claude clients
        self.profile_path = os.path.expanduser("~/.clawdbot_user_profile.md")
        self.data_sources = []

    def gather_data_glm(self):
        """Use GLM (free) to gather and analyze all data sources"""
        gathered = {}

        # 1. Scan project directories
        dirs_to_scan = [
            "~/clawdbot-v2",
            "~/superquant",
            "~/Desktop",
            "~/Documents"
        ]

        for dir_path in dirs_to_scan:
            expanded = os.path.expanduser(dir_path)
            if os.path.exists(expanded):
                # Use GLM to analyze what's in each directory
                files = self._list_files(expanded)
                if files:
                    # GLM analyzes the file list (free, unlimited)
                    analysis = self._glm_analyze(f"What projects/work does this file list suggest about the user?\n{files[:2000]}")
                    gathered[dir_path] = analysis

        # 2. Read key files for context
        key_files = [
            "~/clawdbot-v2/clawdbot.py",
            "~/clawdbot-v2/README.md",
            "~/.clawdbot_memory.json"
        ]

        for file_path in key_files:
            expanded = os.path.expanduser(file_path)
            if os.path.exists(expanded):
                content = self.bot._read_file(expanded)[1]
                # GLM extracts insights (free)
                insights = self._glm_analyze(f"Extract key insights about the user from this file:\n{content[:3000]}")
                gathered[file_path] = insights

        # 3. Check for ChatGPT/Perplexity exports
        export_paths = [
            "~/clawdbot-v2/data/chatgpt_history.json",
            "~/clawdbot-v2/data/perplexity_notes.txt",
            "~/Downloads/conversations.json"
        ]

        for path in export_paths:
            expanded = os.path.expanduser(path)
            if os.path.exists(expanded):
                content = self.bot._read_file(expanded)[1]
                insights = self._glm_analyze(f"Extract user goals, interests, and context from this export:\n{content[:5000]}")
                gathered[path] = insights

        return gathered

    def _glm_analyze(self, prompt):
        """Use GLM-4.7 for analysis (FREE - retry until good)"""
        full_prompt = f"""Analyze this data and extract insights about the user.
Be specific and actionable. Focus on:
- Goals and priorities
- Technical skills
- Work style
- Current projects

{prompt}

Respond with bullet points only."""

        # GLM is free - we can retry
        for attempt in range(3):
            try:
                response = self.bot.glm.chat.completions.create(
                    model="glm-4-flash",
                    messages=[{"role": "user", "content": full_prompt}],
                    max_tokens=1000
                )
                return response.choices[0].message.content
            except:
                continue
        return "Analysis failed"

    def synthesize_profile_claude(self, gathered_data):
        """Use Claude Sonnet ONCE to synthesize final profile"""

        # Compile all GLM analysis
        all_insights = "\n\n".join([
            f"=== {source} ===\n{data}"
            for source, data in gathered_data.items()
        ])

        prompt = f"""You are creating a comprehensive user profile for an AI assistant system.

Based on this gathered data, create a detailed USER_PROFILE.md:

{all_insights}

KNOWN FACTS (from conversation):
- Name: Shamil
- Location: Sandy, Utah
- Job: Amazon warehouse, 6pm-3am shifts
- Getting married soon
- Building: ClawdBot (multi-agent Mac assistant), SuperQuant (trading bot)
- Goals: Make money from Polymarket referrals, Dubco subscriptions, automated trading
- Budget: Unlimited GLM-4.7, limited Claude API
- Style: Elite quality, fast iteration, no patience for broken tools

CREATE THIS EXACT STRUCTURE:

# USER PROFILE: Shamil

## IDENTITY
[Who, where, background]

## CURRENT SITUATION
[Job, schedule, constraints, life context]

## GOALS (Priority Order)
1. [Most important]
2. [Second]
3. [Third]
...

## ACTIVE PROJECTS
### ClawdBot
[Status, what's built, what's next]

### SuperQuant
[Status, challenges]

### Money Generation
[Polymarket strategy, Dubco strategy]

## SKILLS
[Technical skills, learning areas]

## WORK STYLE
[How they like to work, communication style]

## TECH STACK
[Tools, APIs, languages]

## CONSTRAINTS
[Time, money, energy limitations]

## AGENT INSTRUCTIONS
[How all ClawdBot agents should behave based on this profile]

Make it comprehensive and actionable. This profile will be used by all AI agents."""

        response = self.bot.claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=3000,
            messages=[{"role": "user", "content": prompt}]
        )

        return response.content[0].text

    def build_profile(self):
        """Main method - builds complete user profile"""
        print("🔍 Gathering data (GLM - free)...")
        gathered = self.gather_data_glm()

        print(f"📊 Analyzed {len(gathered)} data sources")

        print("🧠 Synthesizing profile (Claude Sonnet - one call)...")
        profile = self.synthesize_profile_claude(gathered)

        # Save profile
        with open(self.profile_path, 'w') as f:
            f.write(profile)

        print(f"✅ Profile saved to {self.profile_path}")
        return profile

    def get_profile(self):
        """Load existing profile"""
        if os.path.exists(self.profile_path):
            with open(self.profile_path, 'r') as f:
                return f.read()
        return None

    def update_profile(self, new_info):
        """Update profile with new information (uses GLM)"""
        current = self.get_profile() or ""

        prompt = f"""Current profile:
{current}

New information to integrate:
{new_info}

Output the updated profile with new info integrated."""

        # Use GLM for updates (free)
        updated = self._glm_analyze(prompt)

        with open(self.profile_path, 'w') as f:
            f.write(updated)

        return updated

    def _list_files(self, directory, max_depth=2):
        """List files in directory"""
        try:
            result = []
            for root, dirs, files in os.walk(directory):
                depth = root.replace(directory, '').count(os.sep)
                if depth < max_depth:
                    for file in files[:20]:  # Limit files per dir
                        result.append(os.path.join(root, file))
            return "\n".join(result[:100])  # Limit total
        except:
            return ""
```

## INTEGRATE INTO CLAWDBOT

Add to end of `clawdbot.py`, before `if __name__ == "__main__":`:

```python
def load_user_profile():
    """Load user profile for context"""
    profile_path = os.path.expanduser("~/.clawdbot_user_profile.md")
    if os.path.exists(profile_path):
        with open(profile_path, 'r') as f:
            return f.read()
    return None
```

Update `__init__` in ClawdBot class:
```python
# Load user profile
self.user_profile = load_user_profile()
```

Update Claude prompts to include profile:
```python
# In claude_complex_task and _create_plan, add to prompt:
if self.user_profile:
    prompt += f"\n\nUSER PROFILE:\n{self.user_profile[:2000]}"
```

## CREATE DIRECTORY STRUCTURE

```bash
mkdir -p ~/clawdbot-v2/agents
touch ~/clawdbot-v2/agents/__init__.py
```

## TEST IT

```python
# In clawdbot.py main, add:
if "--profile" in sys.argv:
    from agents.profiler import ProfilerAgent
    profiler = ProfilerAgent(bot)
    profile = profiler.build_profile()
    print("\n" + "="*50)
    print(profile)
    sys.exit(0)
```

Run: `python clawdbot.py --profile`

## COST ESTIMATE
- GLM calls: ~10-15 calls × $0 = **FREE**
- Claude Sonnet: 1 call × ~$0.02 = **$0.02**
- Total: **~$0.02** for complete user profile

## QUALITY REQUIREMENTS
- Profile must be comprehensive (all sections filled)
- Actionable insights agents can use
- Specific examples from actual projects
- Updated automatically as user shares more info

BUILD THIS NOW. Create the files, test it, make sure it works.
