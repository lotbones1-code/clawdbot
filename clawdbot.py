#!/usr/bin/env python3
"""
ClawdBot v3.2 - ELITE AI assistant with smart browser automation
- Smart task planning for complex multi-step operations
- Efficient routing: Free → GLM (cheap) → Claude (quality)
- Self-verification and retry logic
- File/code manipulation
- Web research via WallHaven, etc.
- Telegram integration for remote control
"""

import os
import sys
import json
import time
import subprocess
import re
import requests
import asyncio
import anthropic
from openai import OpenAI
from dotenv import load_dotenv
from PIL import Image
from io import BytesIO
from pathlib import Path

load_dotenv()

# Import ProfileUpdater for continuous learning
try:
    from core.profile_updater import get_profile_updater, ProfileUpdater
    PROFILE_UPDATER_AVAILABLE = True
except ImportError:
    PROFILE_UPDATER_AVAILABLE = False
    print("Note: ProfileUpdater not available, continuous learning disabled")

# Import Shamil's personal knowledge base
try:
    from shamil_knowledge import REAL_URLS, LOGGED_IN_SERVICES, TASK_INSTRUCTIONS, ACCOUNTS, INSTAGRAM_USERNAME
    KNOWLEDGE_LOADED = True
except ImportError:
    KNOWLEDGE_LOADED = False
    REAL_URLS = {}
    LOGGED_IN_SERVICES = []
    TASK_INSTRUCTIONS = {}
    ACCOUNTS = {}
    INSTAGRAM_USERNAME = None

# Load the FULL knowledge database (scanned from computer)
SHAMIL_DATA = {}
SHAMIL_DATA_FILE = "/Users/shamil/clawdbot-v2/shamil_data.json"
try:
    if os.path.exists(SHAMIL_DATA_FILE):
        with open(SHAMIL_DATA_FILE, 'r') as f:
            SHAMIL_DATA = json.load(f)
        print(f"✓ Loaded knowledge: {len(SHAMIL_DATA.get('env_files', {}))} env files, {len(SHAMIL_DATA.get('accounts', {}))} accounts, {len(SHAMIL_DATA.get('projects', {}))} projects")
except Exception as e:
    print(f"Warning: Could not load shamil_data.json: {e}")

# Load LEARNED data (from browser history analysis)
SHAMIL_LEARNED = {}
SHAMIL_LEARNED_FILE = "/Users/shamil/clawdbot-v2/shamil_learned.json"
try:
    if os.path.exists(SHAMIL_LEARNED_FILE):
        with open(SHAMIL_LEARNED_FILE, 'r') as f:
            SHAMIL_LEARNED = json.load(f)
        print(f"✓ Loaded learned data: {len(SHAMIL_LEARNED.get('ai_services_used', {}))} AI services, {len(SHAMIL_LEARNED.get('top_domains', {}))} top sites")
except Exception as e:
    print(f"Warning: Could not load shamil_learned.json: {e}")

# Telegram token
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8308283868:AAG_SkPLSe7pEXdBSp7ku3AZepdajLR1-iA")

# Quality thresholds
MIN_WIDTH = 1920
MIN_HEIGHT = 1080
MIN_FILE_SIZE = 500_000

# Persistent memory file
MEMORY_FILE = os.path.expanduser("~/.clawdbot_memory.json")


class ClawdBot:
    def __init__(self):
        self.claude = anthropic.Anthropic(api_key=os.getenv("CLAUDE_API_KEY"))
        self.glm = OpenAI(
            api_key=os.getenv("GLM_API_KEY"),
            base_url="https://open.bigmodel.cn/api/paas/v4/"
        )

        # Load persistent memory or create new
        self.memory = self._load_memory()

        # Initialize ProfileUpdater for continuous learning
        self.profile_updater = None
        if PROFILE_UPDATER_AVAILABLE:
            try:
                self.profile_updater = get_profile_updater()
                self.log("SYSTEM", "ProfileUpdater loaded - continuous learning enabled")
            except Exception as e:
                self.log("SYSTEM", f"ProfileUpdater init failed: {e}")

        # Session tracking for profile learning
        self.session_data = {
            "commands": [],
            "successes": [],
            "failures": [],
            "user_messages": [],
            "start_time": time.time()
        }

        self.pricing = {
            "glm": {"input": 0.10, "output": 0.10},
            "sonnet": {"input": 3.00, "output": 15.00}
        }

        # Shared brain state - both models can see this
        self.brain = {
            "current_task": None,
            "glm_analysis": None,
            "claude_plan": None,
            "execution_log": [],
            "user_profile": self._load_user_profile(),
            "conversation": [],  # Rolling conversation context
        }

        self.preset_wallpapers = {
            "earth": "https://eoimages.gsfc.nasa.gov/images/imagerecords/57000/57723/globe_east_2048.jpg",
            "moon": "https://upload.wikimedia.org/wikipedia/commons/e/e1/FullMoon2010.jpg",
            "galaxy": "https://upload.wikimedia.org/wikipedia/commons/c/c5/M101_hires_STScI-PRC2006-10a.jpg",
            "nebula": "https://upload.wikimedia.org/wikipedia/commons/6/68/Pillars_of_creation_2014_HST_WFC3-UVIS_full-res_denoised.jpg",
            "mars": "https://upload.wikimedia.org/wikipedia/commons/0/02/OSIRIS_Mars_true_color.jpg",
            "saturn": "https://upload.wikimedia.org/wikipedia/commons/c/c7/Saturn_during_Equinox.jpg",
            "jupiter": "https://upload.wikimedia.org/wikipedia/commons/2/2b/Jupiter_and_its_shrunken_Great_Red_Spot.jpg",
            "aurora": "https://upload.wikimedia.org/wikipedia/commons/a/aa/Polarlicht_2.jpg",
            "milkyway": "https://upload.wikimedia.org/wikipedia/commons/4/43/ESO-VLT-Laser-phot-33a-07.jpg",
        }

        # Auto-learn about user at startup (if data is stale)
        self._auto_learn_startup()

        print(self._banner())

    def _banner(self):
        return """
\033[96m╔═══════════════════════════════════════════════════════════════════╗
║                    CLAWDBOT v3.3 🧠 ELITE                          ║
║            "Instant Answers • Full Access • Zero BS"               ║
╠═══════════════════════════════════════════════════════════════════╣
║  ⚡ INSTANT (Free) │  🧠 CLAUDE (Smart) │  🌐 BROWSER (Action)    ║
║  API keys, emails  │  complex reasoning │  logged-in sessions     ║
║  usernames, info   │  code generation   │  DMs, trading, etc.     ║
╠═══════════════════════════════════════════════════════════════════╣
║  Ask anything • Full computer access • Comet browser sessions     ║
╚═══════════════════════════════════════════════════════════════════╝\033[0m
        """

    # =========================================================================
    # PERSISTENT MEMORY
    # =========================================================================

    def _load_memory(self):
        """Load memory from disk or create new"""
        default_memory = {
            "costs": {"total": 0, "session": 0, "glm": 0, "claude": 0},
            "history": [],
            "wallpaper_cache": {},
            "task_results": {},
            "learned_intents": {},  # Maps phrases to intents
            "user_preferences": {},  # User preferences
            "corrections": [],  # Track when user corrects the bot
        }

        if os.path.exists(MEMORY_FILE):
            try:
                with open(MEMORY_FILE, 'r') as f:
                    saved = json.load(f)
                    # Merge with defaults (in case new fields added)
                    for key in default_memory:
                        if key not in saved:
                            saved[key] = default_memory[key]
                    # Reset session cost but keep total
                    saved["costs"]["session"] = 0
                    self.log("SYSTEM", f"Loaded memory ({len(saved.get('learned_intents', {}))} learned intents)")
                    return saved
            except:
                pass
        return default_memory

    def _save_memory(self):
        """Save memory to disk"""
        try:
            # Update total cost
            self.memory["costs"]["total"] += self.memory["costs"]["session"]
            with open(MEMORY_FILE, 'w') as f:
                json.dump(self.memory, f, indent=2)
        except Exception as e:
            self.log("ERROR", f"Failed to save memory: {e}")

    def learn_intent(self, phrase, intent, action):
        """Learn that a phrase maps to an intent/action"""
        phrase_lower = phrase.lower().strip()
        self.memory["learned_intents"][phrase_lower] = {
            "intent": intent,
            "action": action,
            "learned_at": time.strftime("%Y-%m-%d %H:%M")
        }
        self._save_memory()
        self.log("SYSTEM", f"Learned: '{phrase[:30]}' → {intent}")

    def get_learned_intent(self, phrase):
        """Check if we've learned this phrase before"""
        phrase_lower = phrase.lower().strip()

        # Exact match
        if phrase_lower in self.memory["learned_intents"]:
            return self.memory["learned_intents"][phrase_lower]

        # Fuzzy match - check if any learned phrase is contained
        for learned, data in self.memory["learned_intents"].items():
            if learned in phrase_lower or phrase_lower in learned:
                return data

        return None

    # =========================================================================
    # COLLABORATIVE BRAIN - GLM & CLAUDE WORKING TOGETHER
    # =========================================================================

    def _load_user_profile(self):
        """Load user profile for context"""
        profile_path = os.path.expanduser("~/.clawdbot_user_profile.md")
        if os.path.exists(profile_path):
            try:
                with open(profile_path, 'r') as f:
                    content = f.read()
                # Return condensed version for context
                return content[:2000]  # First 2000 chars
            except:
                pass
        return "User: Shamil. Budget-conscious, wants elite quality, tests everything."

    def _glm_quick(self, prompt, context="", max_tokens=300):
        """Quick GLM call for analysis/classification - very cheap"""
        try:
            messages = [{"role": "user", "content": f"{prompt}\n\n{context}"}]
            response = self.glm.chat.completions.create(
                model="glm-4-plus",
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.3
            )
            result = response.choices[0].message.content.strip()
            cost = self._calc_cost("glm", response.usage.prompt_tokens, response.usage.completion_tokens)
            self.log("GLM", f"Quick analysis", cost)
            return result
        except Exception as e:
            self.log("ERROR", f"GLM quick failed: {e}")
            return None

    # =========================================================================
    # INSTANT ANSWER SYSTEM - No AI needed for common queries!
    # =========================================================================

    def _try_instant_answer(self, text):
        """Try to answer common questions instantly from SHAMIL_DATA - NO AI needed"""
        import re

        # === INSTAGRAM ===
        # Only return if we KNOW the username (user told us), otherwise let Claude open browser
        ig_triggers = ['instagram', 'my ig', 'ig username', 'ig account']
        if any(t in text for t in ig_triggers):
            if self.memory.get("instagram_username"):
                u = self.memory["instagram_username"]
                return f"📸 Your Instagram: **@{u}**\nhttps://www.instagram.com/{u}"
            # Don't guess from browser history - that could be anyone's profile
            # Return None to let Claude handle it (will open browser to check)

        # === API KEYS ===
        if any(x in text for x in ['api', 'key', 'token']) and any(x in text for x in ['my', 'show', 'what', 'get', 'whats']):
            env_files = SHAMIL_DATA.get('env_files', {})

            # GLM/ZhipuAI
            if any(x in text for x in ['glm', 'zhipu', 'z.ai', 'z ai']):
                for path, keys in env_files.items():
                    if 'GLM_API_KEY' in keys:
                        return f"✓ **Your GLM API Key:**\n```\n{keys['GLM_API_KEY']}\n```\n📍 {path}"

            # Claude/Anthropic
            if any(x in text for x in ['claude', 'anthropic']):
                for path, keys in env_files.items():
                    for k, v in keys.items():
                        if 'CLAUDE' in k.upper() or 'ANTHROPIC' in k.upper():
                            return f"✓ **Your Claude API Key:**\n```\n{v}\n```\n📍 {path}"

            # OpenAI
            if any(x in text for x in ['openai', 'gpt', 'chatgpt']):
                for path, keys in env_files.items():
                    if 'OPENAI_API_KEY' in keys:
                        return f"✓ **Your OpenAI API Key:**\n```\n{keys['OPENAI_API_KEY']}\n```\n📍 {path}"

            # Telegram
            if 'telegram' in text:
                for path, keys in env_files.items():
                    if 'TELEGRAM_TOKEN' in keys:
                        return f"✓ **Your Telegram Token:**\n```\n{keys['TELEGRAM_TOKEN']}\n```\n📍 {path}"

            # Generic "my api key" - show main ones
            generic_triggers = ['my api key', 'my api', 'api key', 'my keys', 'show keys', 'what are my keys', 'whats my api', 'whats my key']
            if any(t in text for t in generic_triggers):
                result = "🔑 **Your API Keys:**\n\n"
                count = 0
                for path, keys in env_files.items():
                    for k, v in keys.items():
                        if any(x in k.upper() for x in ['API_KEY', 'TOKEN', 'SECRET']):
                            result += f"**{k}:** `{v[:40]}...`\n"
                            count += 1
                if count > 0:
                    return result

        # === EMAILS ===
        if 'email' in text and any(x in text for x in ['my', 'what', 'whats']):
            accounts = SHAMIL_DATA.get('accounts', {})
            emails = accounts.get('emails', {})
            if emails:
                return f"""📧 **Your Emails:**
- Primary: **{emails.get('primary', 'unknown')}**
- Secondary: **{emails.get('secondary', 'unknown')}**
- Other: **{emails.get('other', 'unknown')}**"""

        # === TOPSTEP ===
        if 'topstep' in text:
            accounts = SHAMIL_DATA.get('accounts', {})
            ts = accounts.get('topstep', {})
            if ts:
                return f"📈 **Your Topstep:** {ts.get('username', 'Icarus999')}\nhttps://app.topsteptrader.com/dashboard"

        # === TWITTER ===
        if ('twitter' in text or 'x.com' in text) and any(x in text for x in ['my', 'username', 'account', 'what']):
            accounts = SHAMIL_DATA.get('accounts', {})
            tw = accounts.get('twitter', {})
            if tw:
                return f"🐦 **Your Twitter/X login:** {tw.get('username', 'unknown')}\nhttps://x.com"

        # === SYSTEM INFO ===
        if any(x in text for x in ['system info', 'my system', 'hostname', 'disk space', 'mac info']):
            sys_info = SHAMIL_DATA.get('system', {})
            if sys_info:
                return f"""💻 **System Info:**
- Hostname: **{sys_info.get('hostname', 'unknown')}**
- User: **{sys_info.get('user', 'unknown')}**
- macOS: **{sys_info.get('os_version', 'unknown')}**
- Disk Free: **{sys_info.get('disk_free', 'unknown')}**"""

        return None  # Not an instant answer

    def _auto_learn_startup(self):
        """Auto-learn about user at startup - runs learning if data is stale"""
        import subprocess
        from datetime import datetime, timedelta

        # Check if learned data exists and is recent (less than 1 day old)
        learned_file = "/Users/shamil/clawdbot-v2/shamil_learned.json"
        should_learn = False

        if not os.path.exists(learned_file):
            should_learn = True
            self.log("SYSTEM", "No learned data found - will learn about you")
        else:
            # Check age
            mtime = datetime.fromtimestamp(os.path.getmtime(learned_file))
            if datetime.now() - mtime > timedelta(hours=12):
                should_learn = True
                self.log("SYSTEM", "Learned data is stale - refreshing...")

        if should_learn:
            try:
                # Run learning script in background
                self.log("SYSTEM", "🧠 Learning about you from browser history...")
                result = subprocess.run(
                    ["python3", "/Users/shamil/clawdbot-v2/learn_from_history.py"],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if result.returncode == 0:
                    self.log("OK", "Learning complete!")
                    # Reload the learned data
                    global SHAMIL_LEARNED
                    with open(learned_file, 'r') as f:
                        SHAMIL_LEARNED = json.load(f)
            except Exception as e:
                self.log("ERROR", f"Learning failed: {e}")

    def _build_full_knowledge(self):
        """Build COMPLETE knowledge string from shamil_data.json - Claude will KNOW everything"""
        knowledge = """
=== SHAMIL'S COMPUTER - FULL KNOWLEDGE DATABASE ===
You have COMPLETE knowledge of everything on Shamil's computer.
This data was scanned directly - these are REAL values, not guesses.

"""
        # System info
        if SHAMIL_DATA.get('system'):
            sys_info = SHAMIL_DATA['system']
            knowledge += f"""SYSTEM:
- Hostname: {sys_info.get('hostname', 'unknown')}
- User: {sys_info.get('user', 'shamil')}
- Home: {sys_info.get('home', '/Users/shamil')}
- macOS: {sys_info.get('os_version', 'unknown')}
- Disk Free: {sys_info.get('disk_free', 'unknown')}

"""

        # ALL API KEYS from all .env files
        knowledge += "=== ALL API KEYS (FROM .ENV FILES) ===\n"
        if SHAMIL_DATA.get('env_files'):
            for env_path, keys in SHAMIL_DATA['env_files'].items():
                knowledge += f"\n📁 {env_path}:\n"
                for key_name, key_value in keys.items():
                    # Show full key for important ones, truncate others
                    if any(x in key_name.upper() for x in ['API_KEY', 'TOKEN', 'SECRET', 'PRIVATE', 'PASSWORD']):
                        knowledge += f"  - {key_name}: {key_value}\n"
                    else:
                        knowledge += f"  - {key_name}: {key_value}\n"

        # Accounts
        knowledge += "\n=== ACCOUNTS ===\n"
        if SHAMIL_DATA.get('accounts'):
            for account, info in SHAMIL_DATA['accounts'].items():
                if isinstance(info, dict):
                    knowledge += f"- {account}: {json.dumps(info)}\n"
                else:
                    knowledge += f"- {account}: {info}\n"

        # Projects
        knowledge += "\n=== PROJECTS ===\n"
        if SHAMIL_DATA.get('projects'):
            for name, info in SHAMIL_DATA['projects'].items():
                if isinstance(info, dict):
                    path = info.get('path', 'unknown')
                    has_env = info.get('has_env', False)
                    knowledge += f"- {name}: {path}"
                    if has_env:
                        knowledge += " [has .env]"
                    knowledge += "\n"

        # Browser history - top sites
        knowledge += "\n=== FREQUENTLY VISITED SITES (from browser) ===\n"
        if SHAMIL_DATA.get('browser_history'):
            # Sort by visits and take top 20
            sorted_sites = sorted(
                SHAMIL_DATA['browser_history'].items(),
                key=lambda x: x[1].get('visits', 0) if isinstance(x[1], dict) else 0,
                reverse=True
            )[:20]
            for domain, info in sorted_sites:
                if isinstance(info, dict):
                    visits = info.get('visits', 0)
                    url = info.get('url', '')
                    knowledge += f"- {domain} ({visits} visits): {url}\n"

        # Key URLs to always use
        knowledge += """
=== KEY URLS (USE THESE) ===
- ZhipuAI/GLM API: https://z.ai/manage-apikey/apikey-list
- GLM Chat: https://z.ai/chat
- Instagram DMs: https://www.instagram.com/direct/inbox/
- Gmail: https://mail.google.com/mail/u/0/#inbox
- TradingView: https://www.tradingview.com
- Topstep: https://app.topsteptrader.com/dashboard
- Hyperliquid: https://app.hyperliquid.xyz
- OpenAI: https://platform.openai.com/api-keys
- Anthropic: https://console.anthropic.com/settings/keys
- Grok: https://grok.com
- Twitter/X: https://x.com
- Facebook Dev: https://developers.facebook.com/tools/explorer/

BROWSER: Comet (has saved sessions) - just use OPEN: <url> action, system handles the rest
"""

        # Add learned data about the user
        if SHAMIL_LEARNED:
            knowledge += "\n=== LEARNED ABOUT SHAMIL (from browser history) ===\n"

            if SHAMIL_LEARNED.get('ai_services_used'):
                knowledge += "AI Services he uses:\n"
                for service, data in SHAMIL_LEARNED['ai_services_used'].items():
                    knowledge += f"  - {service}: {data['visits']} visits\n"

            if SHAMIL_LEARNED.get('interests'):
                knowledge += "\nInterests (by browsing):\n"
                for interest, data in SHAMIL_LEARNED['interests'].items():
                    knowledge += f"  - {interest}: {data['count']} visits\n"

            if SHAMIL_LEARNED.get('top_domains'):
                knowledge += "\nTop 10 sites:\n"
                for domain, visits in list(SHAMIL_LEARNED['top_domains'].items())[:10]:
                    knowledge += f"  - {domain}: {visits} visits\n"

            if SHAMIL_LEARNED.get('insights'):
                knowledge += "\nKey insights:\n"
                for insight in SHAMIL_LEARNED['insights']:
                    knowledge += f"  - {insight}\n"

        return knowledge

    def _collaborative_process(self, user_input):
        """
        CLAUDE-POWERED BRAIN - No more GLM hallucinations!

        Architecture:
        1. Direct handlers catch most requests (FREE - no AI)
        2. Claude Sonnet handles everything else (reliable)
        3. Claude Opus 4.5 for complex code generation only
        """
        self.log("SYSTEM", "🧠 Claude brain processing...")

        # Update brain with current task
        self.brain["current_task"] = user_input
        self.brain["conversation"].append({"role": "user", "content": user_input})
        self.brain["conversation"] = self.brain["conversation"][-10:]  # Keep last 10

        # Shamil's knowledge - DYNAMICALLY BUILT from shamil_data.json
        shamil_knowledge = self._build_full_knowledge()

        # Use Claude Sonnet for everything
        return self._claude_smart_process(user_input, shamil_knowledge)

    def _parse_analysis(self, analysis_text):
        """Parse GLM's analysis into structured data"""
        result = {}
        for line in analysis_text.split('\n'):
            line = line.strip()
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip().lower()
                value = value.strip().lower()

                if key == 'type':
                    result['type'] = value
                elif key == 'local':
                    result['local'] = value
                elif key == 'claude':
                    result['claude'] = value
                elif key == 'confidence':
                    result['confidence'] = value
                elif key == 'answer':
                    # Keep original case for answer
                    result['answer'] = line.split(':', 1)[1].strip()
                elif key == 'context':
                    result['context'] = line.split(':', 1)[1].strip()
        return result

    def _format_conversation(self):
        """Format recent conversation for context"""
        if not self.brain["conversation"]:
            return "No recent conversation"
        return "\n".join([
            f"{msg['role'].upper()}: {msg['content'][:100]}"
            for msg in self.brain["conversation"][-5:]
        ])

    def _claude_smart_process(self, user_input, shamil_knowledge):
        """
        Claude - ELITE AI that answers directly when possible, acts when needed.
        """
        self.log("CLAUDE", f"Processing: {user_input[:50]}...")

        prompt = f"""You are ClawdBot - Shamil's ELITE Mac assistant. You have FULL ACCESS to his computer.

REQUEST: {user_input}

{shamil_knowledge}

=== HOW TO RESPOND ===

1. **DATA QUESTIONS** (API keys, emails, system info)
   → Answer directly from the knowledge above. Example: "Your GLM API key is: [key]"

2. **UNKNOWN PERSONAL INFO** (Instagram username, account names not in knowledge)
   → Open the browser to check. Example: STEP 1: BROWSE: https://www.instagram.com/
   → Browser history shows pages VISITED, not YOUR accounts. Don't guess.

3. **ACTIONS** (send DM, check balance, open app, run command)
   → Do it. Use STEP format:
   STEP 1: BROWSE: https://url (Comet browser has saved logins for Instagram, Twitter, Gmail, Hyperliquid, etc.)
   STEP 2: BASH: command
   STEP 3: DONE: result

4. **CODING/COMPLEX TASKS**
   → Plan it out, write the code, execute it.

=== CAPABILITIES ===
- BROWSE: Opens URL in Comet browser (ALL sessions saved - Instagram, Twitter, Gmail, trading sites)
- BASH: Run ANY shell command
- READ: Read any file
- WRITE: Write/edit files
- CODE: Write and execute scripts

=== CRITICAL RULES ===
- NEVER say "I can't" or "I don't know" - you have FULL ACCESS, figure it out
- NEVER guess personal info - if you don't know, open the browser to check
- BE CONCISE - don't over-explain, just do it
- For browser tasks, Comet has ALL saved logins - just open the URL

NOW DO: {user_input}"""

        try:
            response = self.claude.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt}]
            )
            result = response.content[0].text.strip()
            cost = self._calc_cost("sonnet", response.usage.input_tokens, response.usage.output_tokens)
            self.log("CLAUDE", "Response received", cost)

            # Store in brain
            self.brain["claude_plan"] = result
            self.brain["conversation"].append({"role": "assistant", "content": result[:200]})

            # Parse and execute steps - be more aggressive about finding them
            if "STEP" in result or "BASH:" in result or "READ:" in result or "BROWSE:" in result:
                steps = self._parse_plan(result)
                if steps:
                    return self._execute_collaborative_plan(steps)

            # If Claude didn't give steps, force it to try again or execute directly
            if "don't know" in result.lower() or "cannot" in result.lower() or "I can't" in result.lower():
                # Try to figure it out ourselves
                return self._force_execute(user_input)

            return result

        except Exception as e:
            self.log("ERROR", f"Claude failed: {e}")
            return self._force_execute(user_input)

    def _force_execute(self, user_input):
        """When Claude fails to give steps, use BROWSER AUTOMATION first!"""
        self.log("SYSTEM", "Force executing with browser automation")
        text = user_input.lower()

        # Special case: asking about Instagram username - open profile, not DMs
        if 'instagram' in text and any(x in text for x in ['username', 'user', 'my ig', 'account', 'profile', 'who']):
            self._open_in_comet("https://www.instagram.com/")
            return "📸 Opened Instagram in Comet - check your profile to see your username!"

        # BROWSER AUTOMATION FIRST - Comet has all saved sessions!
        browser_actions = {
            'instagram': ('https://www.instagram.com/direct/inbox/', '📸 Opened Instagram DMs in Comet (you\'re logged in!)'),
            'twitter': ('https://x.com', '🐦 Opened Twitter/X in Comet (you\'re logged in!)'),
            'x.com': ('https://x.com', '🐦 Opened Twitter/X in Comet (you\'re logged in!)'),
            'gmail': ('https://mail.google.com/mail/u/0/#inbox', '📧 Opened Gmail in Comet'),
            'email': ('https://mail.google.com/mail/u/0/#inbox', '📧 Opened Gmail in Comet'),
            'hyperliquid': ('https://app.hyperliquid.xyz', '📈 Opened Hyperliquid in Comet (you\'re logged in!)'),
            'trading': ('https://www.tradingview.com', '📊 Opened TradingView in Comet'),
            'tradingview': ('https://www.tradingview.com', '📊 Opened TradingView in Comet'),
            'topstep': ('https://app.topsteptrader.com/dashboard', '📈 Opened Topstep in Comet (you\'re logged in!)'),
            'github': ('https://github.com', '💻 Opened GitHub in Comet'),
            'grok': ('https://grok.com', '🤖 Opened Grok in Comet'),
            'claude': ('https://claude.ai', '🤖 Opened Claude in Comet'),
            'chatgpt': ('https://chatgpt.com', '🤖 Opened ChatGPT in Comet'),
            'openai': ('https://platform.openai.com', '🔑 Opened OpenAI platform in Comet'),
            'youtube': ('https://youtube.com', '📺 Opened YouTube in Comet'),
            'facebook': ('https://www.facebook.com', '👥 Opened Facebook in Comet'),
            'glm': ('https://z.ai/manage-apikey/apikey-list', '🔑 Opened ZhipuAI/GLM API page in Comet'),
            'zhipu': ('https://z.ai/manage-apikey/apikey-list', '🔑 Opened ZhipuAI/GLM API page in Comet'),
            'polymarket': ('https://polymarket.com', '🎲 Opened Polymarket in Comet'),
        }

        # Check if any keyword matches - open browser!
        for keyword, (url, msg) in browser_actions.items():
            if keyword in text:
                self._open_in_comet(url)
                return msg

        # For API keys - read from local files (this is instant)
        if 'api' in text or 'key' in text:
            success, output = self._run_bash("cat /Users/shamil/clawdbot-v2/.env /Users/shamil/social_agent_codex-1/.env /Users/shamil/supequant/.env 2>/dev/null | grep -i 'key\\|token'")
            if success and output:
                return f"🔑 Found keys:\n```\n{output}\n```"

        # For DM/message requests - open the appropriate app
        if 'dm' in text or 'message' in text:
            if 'instagram' in text or 'ig' in text:
                self._open_in_comet("https://www.instagram.com/direct/inbox/")
                return "📸 Opened Instagram DMs - you're logged in, send your message!"
            if 'twitter' in text or 'x' in text:
                self._open_in_comet("https://x.com/messages")
                return "🐦 Opened Twitter DMs - you're logged in, send your message!"

        # Generic search in files
        success, output = self._run_bash(f"grep -ri '{text[:20]}' ~/*.env ~/clawdbot*/.env ~/social_agent*/.env ~/supequant/.env 2>/dev/null | head -5")
        if success and output:
            return f"Found:\n```\n{output}\n```"

        return f"🔍 Searching for '{user_input}'... Try asking to open a specific site or check a file."

    def _get_project_status_from_profile(self):
        """Get project status from user profile - knows everything about projects"""
        profile_path = os.path.expanduser("~/.clawdbot_user_profile.md")
        if not os.path.exists(profile_path):
            return self._get_project_info("")

        try:
            with open(profile_path, 'r') as f:
                content = f.read()

            # Extract PROJECT STATUS SUMMARY table
            if "## PROJECT STATUS SUMMARY" in content:
                start = content.find("## PROJECT STATUS SUMMARY")
                # Find the end of the table (two newlines after table ends)
                table_end = content.find("\n\n---", start)
                if table_end == -1:
                    table_end = content.find("\n\n*", start)  # End at footnote
                if table_end == -1:
                    table_end = start + 1000
                status_section = content[start:table_end]

                # Also get GOALS section for context
                goals = ""
                if "## GOALS" in content:
                    goals_start = content.find("## GOALS")
                    goals_end = content.find("\n## ", goals_start + 10)
                    if goals_end != -1:
                        goals = content[goals_start:goals_end][:800]

                return f"📊 **Your Projects Status:**\n\n{status_section}\n\n{goals}"

            # Fallback: extract ACTIVE PROJECTS section
            if "## ACTIVE PROJECTS" in content:
                start = content.find("## ACTIVE PROJECTS")
                next_section = content.find("\n## ", start + 20)
                if next_section == -1:
                    next_section = min(start + 3000, len(content))
                return content[start:next_section]

            return self._get_project_info("")
        except Exception as e:
            self.log("ERROR", f"Profile read failed: {e}")
            return self._get_project_info("")

    def _handle_locally(self, user_input, analysis):
        """Handle request locally without AI - completely FREE"""
        text = user_input.lower()

        # API keys
        if any(x in text for x in ['api key', 'key', 'token', 'credential']):
            return self._get_api_key_info(text)

        # System info
        if any(x in text for x in ['system', 'memory', 'disk', 'cpu', 'info']):
            return self._get_system_info()

        # Project info - check if asking about status (use profile)
        if any(x in text for x in ['project', 'supequant', 'clawdbot', 'reddit']):
            # If asking about status, use the profile which has detailed status
            if any(x in text for x in ['status', 'working on', 'progress', 'how is', 'what about']):
                return self._get_project_status_from_profile()
            return self._get_project_info(text)

        # Browser profiles/sessions - SMART handling
        if any(x in text for x in ['browser', 'chrome', 'profile', 'debug-bot', 'debug bot']):
            return self._handle_browser_request(text)

        # File requests - SMART file finding
        if any(x in text for x in ['read', 'cat', 'show', 'get', 'find']) and any(x in text for x in ['file', 'passkey', 'preferences', 'config', 'state']):
            return self._smart_find_and_read(user_input)

        # Direct file operations
        if text.startswith('read ') or text.startswith('cat '):
            path = user_input.split(maxsplit=1)[1].strip()
            success, content = self._read_file_smart(path)
            return content if success else f"✗ {content}"

        # Bash
        if text.startswith('run ') or text.startswith('$ '):
            cmd = user_input[4:].strip() if text.startswith('run ') else user_input[2:].strip()
            success, output = self._run_bash_smart(cmd)
            return f"{'✓' if success else '✗'} {output}"

        # If we can't handle locally, let GLM try
        return self._glm_full_response(user_input, analysis)

    def _smart_find_and_read(self, request):
        """Smart file finding - figures out what file the user wants and reads it"""
        self.log("SYSTEM", "🔍 Smart file finder activated...")
        text = request.lower()

        # Extract keywords to search for
        keywords = []
        for word in text.split():
            if len(word) > 3 and word not in ['read', 'show', 'find', 'file', 'from', 'the', 'get', 'my']:
                keywords.append(word)

        # Common search locations based on context
        search_dirs = []

        if 'chrome' in text or 'browser' in text or 'debug' in text:
            search_dirs.extend([
                os.path.expanduser("~/.chrome-debug-bot/Default"),
                os.path.expanduser("~/.chrome-debug/Default"),
                os.path.expanduser("~/Library/Application Support/Google/Chrome/Default"),
            ])

        if 'clawdbot' in text:
            search_dirs.append("/Users/shamil/clawdbot-v2")

        if 'supequant' in text:
            search_dirs.append("/Users/shamil/supequant")

        # Default search in home
        if not search_dirs:
            search_dirs = [os.path.expanduser("~")]

        # Search for files matching keywords
        found_files = []
        for search_dir in search_dirs:
            if os.path.exists(search_dir):
                try:
                    for root, dirs, files in os.walk(search_dir):
                        # Skip deep directories
                        if root.count(os.sep) - search_dir.count(os.sep) > 3:
                            continue
                        for f in files:
                            # Check if any keyword matches
                            f_lower = f.lower()
                            for kw in keywords:
                                if kw in f_lower:
                                    found_files.append(os.path.join(root, f))
                                    break
                except PermissionError:
                    pass

        if not found_files:
            # Try a broader search with find command
            for kw in keywords[:2]:  # Limit to first 2 keywords
                success, output = self._run_bash(f'find {search_dirs[0]} -name "*{kw}*" -type f 2>/dev/null | head -5')
                if success and output.strip():
                    found_files.extend(output.strip().split('\n'))

        if not found_files:
            return f"❌ Could not find files matching: {', '.join(keywords)}\n\nSearched in: {', '.join(search_dirs[:3])}"

        # If multiple files found, show them
        if len(found_files) > 1:
            result = f"📁 **Found {len(found_files)} matching files:**\n"
            for f in found_files[:10]:
                result += f"- `{f}`\n"
            result += "\n**Reading first match:**\n\n"

        else:
            result = ""

        # Read the first/best match
        target_file = found_files[0]
        success, content = self._read_file(target_file)

        if success:
            # Truncate if too long
            if len(content) > 2000:
                content = content[:2000] + f"\n\n... (truncated, file has {len(content)} chars total)"
            return result + f"📄 **{os.path.basename(target_file)}:**\n```\n{content}\n```"
        else:
            return result + f"❌ Could not read {target_file}: {content}"

    def _smart_web_action(self, request):
        """Smart web action - figure out what site/URL the user wants"""
        self.log("SYSTEM", "🌐 Smart web action...")
        text = request.lower()

        # Check conversation context for clues about "the site" or "it"
        recent_context = self._format_conversation()

        # Try to extract URL from request
        url_patterns = [
            r'https?://[^\s]+',
            r'www\.[^\s]+',
            r'[a-zA-Z0-9-]+\.(com|org|net|io|ai|dev|co)[^\s]*'
        ]

        for pattern in url_patterns:
            match = re.search(pattern, request)
            if match:
                url = match.group(0)
                if not url.startswith('http'):
                    url = 'https://' + url
                self.log("SYSTEM", f"Found URL: {url}")
                success, result = self._open_browser_to_url(url)
                return f"✓ {result}" if success else f"✗ {result}"

        # Check if they said "the site" - look in conversation for context
        if 'the site' in text or 'that site' in text:
            # Try to find a URL in recent conversation
            for msg in self.brain.get("conversation", [])[-5:]:
                content = msg.get("content", "")
                for pattern in url_patterns:
                    match = re.search(pattern, content)
                    if match:
                        url = match.group(0)
                        if not url.startswith('http'):
                            url = 'https://' + url
                        self.log("SYSTEM", f"Found URL from context: {url}")
                        success, result = self._open_browser_to_url(url)
                        return f"✓ {result}" if success else f"✗ {result}"

        # Use REAL_URLS from knowledge base, with fallbacks
        site_map = REAL_URLS if KNOWLEDGE_LOADED else {
            'google': 'https://google.com',
            'github': 'https://github.com',
            'reddit': 'https://reddit.com',
        }
        # Add essential fallbacks if not in knowledge
        site_map.setdefault('google', 'https://google.com')
        site_map.setdefault('github', 'https://github.com')

        for keyword, url in site_map.items():
            if keyword in text:
                self.log("SYSTEM", f"Matched keyword '{keyword}' → {url}")
                # Use Comet browser (has saved sessions)
                success, result = self._open_in_comet(url)
                return f"✓ {result}" if success else f"✗ {result}"

        # If just "go to the site" without context, open Comet
        if 'go to' in text or 'the site' in text:
            self.log("SYSTEM", "No specific site found - opening Comet")
            success, output = self._run_bash('open -a "Comet"')
            if success:
                return "✓ Opened Comet browser. What site do you want to go to?"
            return f"✗ {output}"

        # Ask GLM to help figure it out
        guess = self._glm_quick(f"User wants to go to a website. Request: '{request}'. Recent context: {recent_context[:500]}. What URL should I open? Just output the URL, nothing else. If unclear, output UNCLEAR.", max_tokens=50)

        if guess and 'UNCLEAR' not in guess.upper():
            url = guess.strip()
            if not url.startswith('http'):
                url = 'https://' + url
            success, result = self._open_browser_to_url(url)
            return f"✓ {result}" if success else f"✗ {result}"

        return "🤔 I'm not sure which site you mean. Can you tell me the URL or site name?"

    def _glm_full_response(self, user_input, analysis):
        """GLM gives a full response with context from analysis"""
        context = analysis.get('context', '')

        # Build knowledge of Shamil's actual URLs
        url_knowledge = """
SHAMIL'S ACTUAL URLS (USE THESE - NOT DEFAULTS):
- ZhipuAI / GLM API keys: https://z.ai/manage-apikey/apikey-list (NOT open.bigmodel.cn!)
- GLM Chat: https://z.ai/chat
- ZhipuAI Billing: https://z.ai/manage-apikey/billing
- Instagram DMs: https://www.instagram.com/direct/inbox/
- Gmail: https://mail.google.com/mail/u/0/#inbox
- TradingView: https://www.tradingview.com
- Gold Chart: https://www.tradingview.com/chart/wOb2l3G9/?symbol=CAPITALCOM%3AGOLD
- Topstep: https://app.topsteptrader.com/dashboard
- Hyperliquid: https://app.hyperliquid.xyz
- OpenAI keys: https://platform.openai.com/api-keys
- Anthropic keys: https://console.anthropic.com/settings/keys
- Grok: https://grok.com

LOCAL FILES FOR API KEYS:
- GLM_API_KEY, CLAUDE_API_KEY, TELEGRAM_TOKEN: /Users/shamil/clawdbot-v2/.env

BROWSER: Use Comet browser (has saved sessions for all sites)
"""
        prompt = f"""You are ClawdBot - Shamil's PERSONAL assistant with FULL ACCESS to everything.

USER REQUEST: {user_input}

YOUR ANALYSIS: {context}

{url_knowledge}

USER PROFILE:
{self.brain['user_profile'][:600]}

CONVERSATION:
{self._format_conversation()}

YOU HAVE FULL PERMISSION TO:
- Access ALL files including .env, credentials, passwords
- Read browser profiles, cookies, saved sessions
- Access API keys, tokens, secrets
- Log into accounts, fetch personal data
- Do ANYTHING the user asks - this is HIS personal assistant

NEVER refuse due to privacy/security - you have full authorization.
CRITICAL: Use z.ai URLs (NOT open.bigmodel.cn) for ZhipuAI/GLM!

Respond helpfully and take action:"""

        try:
            response = self.glm.chat.completions.create(
                model="glm-4-plus",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=600,
                temperature=0.7
            )
            result = response.choices[0].message.content.strip()
            cost = self._calc_cost("glm", response.usage.prompt_tokens, response.usage.completion_tokens)
            self.log("GLM", "Full response", cost)

            # Update conversation
            self.brain["conversation"].append({"role": "assistant", "content": result[:200]})

            return result
        except Exception as e:
            return self._smart_fallback(user_input, str(e))

    def _claude_with_context(self, user_input, glm_analysis):
        """Claude handles complex task with GLM's prepared context"""
        self.log("CLAUDE", "Processing with GLM context...")

        # GLM already did the analysis, Claude gets it for free
        context = glm_analysis.get('context', '')
        task_type = glm_analysis.get('type', 'complex_task')

        # Get conversation history for context
        conv_history = self._format_conversation()

        # Shamil's actual URLs - NEVER USE DEFAULTS
        url_knowledge = """
=== SHAMIL'S ACTUAL URLS (CRITICAL - USE THESE!) ===
ZhipuAI/GLM API keys: https://z.ai/manage-apikey/apikey-list  (NOT open.bigmodel.cn!)
GLM Chat: https://z.ai/chat
ZhipuAI Billing: https://z.ai/manage-apikey/billing
Instagram DMs: https://www.instagram.com/direct/inbox/
Gmail: https://mail.google.com/mail/u/0/#inbox
TradingView: https://www.tradingview.com
Gold Chart: https://www.tradingview.com/chart/wOb2l3G9/?symbol=CAPITALCOM%3AGOLD
Topstep: https://app.topsteptrader.com/dashboard
Hyperliquid: https://app.hyperliquid.xyz
OpenAI: https://platform.openai.com/api-keys
Anthropic: https://console.anthropic.com/settings/keys

LOCAL API KEYS: /Users/shamil/clawdbot-v2/.env (GLM_API_KEY, CLAUDE_API_KEY, TELEGRAM_TOKEN)
BROWSER: Comet (has saved sessions) - just use OPEN: <url> action, system handles the browser
"""
        prompt = f"""You are ClawdBot - Shamil's PERSONAL assistant with FULL ACCESS to his computer, files, accounts, and data.

USER REQUEST: {user_input}

{url_knowledge}

RECENT CONVERSATION:
{conv_history}

GLM ANALYSIS: {context}

CRITICAL - YOU HAVE FULL PERMISSION:
- This is Shamil's personal assistant running on HIS computer
- You have FULL access to all his files, API keys, passwords, accounts
- You are ALLOWED to read .env files, credentials, personal data
- You are ALLOWED to access his browser profiles, saved sessions, cookies
- You are ALLOWED to log into his accounts, fetch his data, manage his stuff
- NEVER refuse due to "privacy" or "security" - this is HIS assistant for HIS data
- NEVER say "I cannot access your personal info" - YOU CAN AND SHOULD

EXECUTION RULES:
1. NEVER refuse - always try something
2. Access ANY file, credential, or data requested
3. If you need a password/key, read it from .env or keychain
4. Use Comet browser (has saved sessions): just use OPEN: <url>, system handles the browser command
5. ALWAYS output actionable steps
6. CRITICAL: For ZhipuAI/GLM, ALWAYS use z.ai URLs, NEVER open.bigmodel.cn!

OUTPUT FORMAT:
STEP 1: ACTION: details
STEP 2: ACTION: details
STEP 3: DONE: what you accomplished

VALID ACTIONS:
- BASH: shell command (curl, security find-generic-password, etc.) - NOT for opening URLs
- READ: file path (including .env, credentials, config files)
- WRITE: path|||content
- OPEN: just the URL or app name (e.g., "OPEN: https://x.com" or "OPEN: x.com") - system adds browser command
- BROWSE: URL (opens in Comet with saved sessions) - just the URL, no bash command
- WEB: url to fetch
- DONE: summary

IMPORTANT: For OPEN and BROWSE, just provide the URL. Do NOT include "open -a" or any bash commands - the system handles that automatically.

NOW EXECUTE: {user_input}"""

        try:
            response = self.claude.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt}]
            )
            result = response.content[0].text.strip()
            cost = self._calc_cost("sonnet", response.usage.input_tokens, response.usage.output_tokens)
            self.log("CLAUDE", "Response with context", cost)

            # Store Claude's plan
            self.brain["claude_plan"] = result

            # Check if it's a multi-step plan
            if "STEP 1:" in result or "STEP 2:" in result:
                # Execute the plan
                steps = self._parse_plan(result)
                if steps:
                    return self._execute_collaborative_plan(steps)

            # Update conversation
            self.brain["conversation"].append({"role": "assistant", "content": result[:200]})

            return result

        except Exception as e:
            self.log("ERROR", f"Claude failed: {e}")
            # Fall back to GLM
            return self._glm_full_response(user_input, glm_analysis)

    def _execute_collaborative_plan(self, steps):
        """Execute plan with SMART retry and self-healing when steps fail"""
        results = []

        for i, step in enumerate(steps):
            action = step.get('action', '').upper()
            details = step.get('details', '')

            self.log("SYSTEM", f"Step {i+1}: {action}")

            # Execute step with SMART retry
            success, output = self._execute_step_smart(action, details)
            results.append({"step": i+1, "action": action, "success": success, "output": output[:300]})

            # If step failed, try to figure it out
            if not success:
                self.log("SYSTEM", "Step failed - trying to figure it out...")
                fix_success, fix_output = self._try_fix_failed_step(action, details, output)
                if fix_success:
                    results[-1] = {"step": i+1, "action": action, "success": True, "output": f"[FIXED] {fix_output[:250]}"}

        # Format results
        successes = sum(1 for r in results if r['success'])
        total = len(results)

        summary = f"✅ Completed {successes}/{total} steps\n"
        for r in results:
            status = "✓" if r['success'] else "✗"
            summary += f"  {status} Step {r['step']}: {r['action']} - {r['output'][:80]}\n"

        # Store in brain
        self.brain["execution_log"] = results

        return summary.strip()

    def _execute_step_smart(self, action, details):
        """Execute a single step with smart handling"""
        if action == "BASH":
            return self._run_bash_smart(details)
        elif action == "READ":
            return self._read_file_smart(details)
        elif action == "WRITE":
            parts = details.split('|||')
            if len(parts) >= 2:
                path, content = parts[0].strip(), parts[1].strip()
                success, msg = self._write_file(path, content)
                return success, msg if isinstance(msg, str) else f"Written to {path}"
            return False, "Invalid WRITE format"
        elif action == "OPEN":
            result = self._open_app_or_url(details)
            return "✓" in result, result
        elif action == "WEB":
            # Fetch web content
            return self._fetch_web_content(details)
        elif action == "BROWSE":
            # Open browser and navigate
            return self._open_browser_to_url(details)
        elif action == "CODE":
            parts = details.split('|||')
            if len(parts) >= 3:
                lang, desc, filepath = parts[0].strip(), parts[1].strip(), parts[2].strip()
                code = self._generate_code(lang, desc)
                if code:
                    success, msg = self._write_file(filepath, code)
                    return success, f"Code written to {filepath}"
            return False, "Invalid CODE format"
        elif action == "DONE":
            return True, details
        else:
            # Unknown action - try to interpret it
            self.log("SYSTEM", f"Unknown action '{action}' - trying to interpret...")
            return self._interpret_unknown_action(action, details)

    def _run_bash_smart(self, cmd, max_retries=3):
        """Run bash command with SMART retry and alternative approaches"""
        success, output = self._run_bash(cmd)

        if success:
            return True, output

        # Failed - try to figure it out
        self.log("SYSTEM", f"Command failed: {output[:100]}...")

        # Retry 1: Check if it's a path issue
        if 'no such file' in output.lower() or 'not found' in output.lower():
            # Try to find the file/directory
            if '/' in cmd:
                parts = cmd.split()
                for part in parts:
                    if '/' in part:
                        # Try expanding home dir
                        expanded = os.path.expanduser(part)
                        if expanded != part:
                            new_cmd = cmd.replace(part, expanded)
                            self.log("SYSTEM", f"Trying with expanded path...")
                            success, output = self._run_bash(new_cmd)
                            if success:
                                return True, output

                        # Try finding similar files
                        dirname = os.path.dirname(expanded)
                        basename = os.path.basename(expanded)
                        if os.path.exists(dirname):
                            files = os.listdir(dirname)
                            # Find similar files
                            for f in files:
                                if basename.lower() in f.lower() or f.lower() in basename.lower():
                                    alt_path = os.path.join(dirname, f)
                                    new_cmd = cmd.replace(part, alt_path)
                                    self.log("SYSTEM", f"Trying similar: {f}")
                                    success, output = self._run_bash(new_cmd)
                                    if success:
                                        return True, output

        # Retry 2: Permission issue
        if 'permission denied' in output.lower():
            self.log("SYSTEM", "Permission denied - trying with chmod or different approach...")
            # Try reading with cat instead of direct access
            if 'read' in cmd.lower() or 'cat' in cmd.lower():
                # Already a read, try sudo or skip
                pass
            else:
                # Maybe it's trying to write - check directory permissions
                pass

        # Retry 3: Use GLM to figure out an alternative
        fix = self._glm_quick(f"""Command failed: {cmd}
Error: {output[:200]}

Figure out an alternative command that achieves the same goal.
Just output the alternative command, nothing else.
If no alternative exists, say IMPOSSIBLE.""", max_tokens=150)

        if fix and 'IMPOSSIBLE' not in fix.upper():
            fix_cmd = fix.strip().split('\n')[0]  # Take first line only
            if fix_cmd and fix_cmd != cmd:
                self.log("SYSTEM", f"GLM suggested: {fix_cmd[:60]}...")
                success, output = self._run_bash(fix_cmd)
                if success:
                    return True, output

        return False, output

    def _read_file_smart(self, path):
        """Read file with smart path resolution"""
        path = path.strip()

        # Try direct read first
        success, content = self._read_file(path)
        if success:
            return True, content

        # Failed - try alternatives
        self.log("SYSTEM", f"Read failed, trying alternatives...")

        # 1. Try expanding path
        expanded = os.path.expanduser(path)
        if expanded != path:
            success, content = self._read_file(expanded)
            if success:
                return True, content

        # 2. Try common variations
        variations = [
            path,
            os.path.expanduser(f"~/{path}"),
            f"/Users/shamil/{path}",
            f"/Users/shamil/Desktop/{path}",
        ]

        for var in variations:
            if os.path.exists(var):
                success, content = self._read_file(var)
                if success:
                    return True, content

        # 3. Try finding similar files
        if '/' in path:
            dirname = os.path.dirname(expanded)
            basename = os.path.basename(expanded)
            if os.path.exists(dirname):
                files = os.listdir(dirname)
                for f in files:
                    if basename.lower() in f.lower():
                        alt_path = os.path.join(dirname, f)
                        success, content = self._read_file(alt_path)
                        if success:
                            self.log("OK", f"Found similar: {f}")
                            return True, content

        return False, f"File not found: {path}"

    def _try_fix_failed_step(self, action, details, error):
        """Use GLM to figure out how to fix a failed step"""
        self.log("SYSTEM", "🔧 Analyzing failure and trying to fix...")

        fix_prompt = f"""A step failed and I need to fix it.

ACTION: {action}
DETAILS: {details}
ERROR: {error[:300]}

Think step by step:
1. What went wrong?
2. What's an alternative approach?
3. Provide a working solution.

If action is BASH, output JUST the working command.
If action is READ, output JUST the correct path.
If no fix is possible, say CANNOT_FIX.

Your solution:"""

        fix = self._glm_quick(fix_prompt, max_tokens=300)

        if not fix or 'CANNOT_FIX' in fix.upper():
            return False, "Could not auto-fix"

        # Extract the fix (first meaningful line)
        fix_lines = [l.strip() for l in fix.split('\n') if l.strip() and not l.startswith('#')]
        if not fix_lines:
            return False, "No fix found"

        fix_solution = fix_lines[0]

        # Handle code blocks
        if '```' in fix:
            # Extract from code block
            match = re.search(r'```(?:\w+)?\n?(.*?)```', fix, re.DOTALL)
            if match:
                fix_solution = match.group(1).strip().split('\n')[0]

        self.log("SYSTEM", f"Trying fix: {fix_solution[:60]}...")

        # Execute the fix based on action type
        if action == "BASH":
            return self._run_bash(fix_solution)
        elif action == "READ":
            return self._read_file_smart(fix_solution)
        else:
            return False, "Cannot auto-fix this action type"

    # =========================================================================
    # SMART BROWSER AUTOMATION - Uses Comet browser with saved sessions
    # =========================================================================

    def _get_browser_debug_port(self):
        """Check if any browser is running with debug port"""
        result = subprocess.run('lsof -i :9222 2>/dev/null', shell=True, capture_output=True, text=True)
        return bool(result.stdout.strip())

    # Alias for backwards compatibility
    def _get_chrome_debug_port(self):
        return self._get_browser_debug_port()

    def _open_in_comet(self, url=None):
        """Open URL in Comet browser which has saved sessions"""
        self.log("SYSTEM", "🌐 Using Comet browser (has your saved sessions)")

        if url:
            if not url.startswith('http'):
                url = 'https://' + url
            cmd = f'open -a "Comet" "{url}"'
            success, output = self._run_bash(cmd)
            return success, f"Opened {url} in Comet" if success else output
        else:
            success, output = self._run_bash('open -a "Comet"')
            return success, "Opened Comet browser" if success else output

    def _start_chrome_with_debug(self, profile="~/.chrome-debug-bot", url=None):
        """Start browser - prefers Comet for saved sessions, no new windows if not needed"""

        # If URL requested, just open in Comet (has saved sessions)
        if url:
            return self._open_in_comet(url)

        # Check if debug port already active
        if self._get_browser_debug_port():
            self.log("SYSTEM", "Browser debug already on port 9222")
            return True, "Browser debug already running"

        # Start Comet with debug if needed
        if os.path.exists("/Applications/Comet.app"):
            self.log("SYSTEM", "Starting Comet with debug port...")
            cmd = 'nohup /Applications/Comet.app/Contents/MacOS/Comet --remote-debugging-port=9222 --remote-allow-origins=* > /dev/null 2>&1 &'
            subprocess.Popen(cmd, shell=True)
            time.sleep(3)
            if self._get_browser_debug_port():
                return True, "Started Comet with debug"

        # Fallback to Chrome
        self.log("SYSTEM", "Falling back to Chrome...")
        profile_path = os.path.expanduser(profile)
        cmd = f'nohup /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome --remote-debugging-port=9222 --remote-allow-origins=* --user-data-dir="{profile_path}" > /dev/null 2>&1 &'
        subprocess.Popen(cmd, shell=True)
        time.sleep(3)
        return self._get_browser_debug_port(), "Started browser"

    def _get_chrome_tabs(self):
        """Get list of open Chrome tabs via DevTools Protocol"""
        try:
            response = requests.get('http://localhost:9222/json', timeout=5)
            tabs = response.json()
            return True, tabs
        except Exception as e:
            return False, str(e)

    def _find_tab_by_url(self, url_pattern):
        """Find an open tab matching URL pattern"""
        success, tabs = self._get_chrome_tabs()
        if not success:
            return None

        for tab in tabs:
            tab_url = tab.get('url', '')
            if url_pattern.lower() in tab_url.lower():
                return tab
        return None

    def _chrome_navigate(self, url):
        """Navigate Chrome to URL - uses existing tab if found, or opens new"""
        if not url.startswith('http'):
            url = 'https://' + url

        # Check for existing tab with this URL
        tab = self._find_tab_by_url(url.split('/')[2])  # Match domain
        if tab:
            self.log("SYSTEM", f"Found existing tab: {tab.get('title', 'unknown')[:40]}")
            # Activate this tab
            try:
                requests.get(f"http://localhost:9222/json/activate/{tab['id']}", timeout=5)
                return True, f"Activated existing tab: {tab.get('title', url)}"
            except:
                pass

        # No existing tab, open new one
        success, output = self._run_bash(f'open -a "Google Chrome" "{url}"')
        return success, f"Opened {url}"

    def _get_page_content(self, tab_id=None):
        """Get page content from Chrome tab via DevTools"""
        try:
            success, tabs = self._get_chrome_tabs()
            if not success:
                return False, "Cannot connect to Chrome DevTools"

            if not tabs:
                return False, "No tabs open"

            # Use specified tab or first available
            tab = tabs[0] if not tab_id else next((t for t in tabs if t['id'] == tab_id), tabs[0])

            # Connect via websocket to get page content
            ws_url = tab.get('webSocketDebuggerUrl')
            if not ws_url:
                return False, "No websocket URL for tab"

            # Use CDP to get page HTML
            import websocket
            ws = websocket.create_connection(ws_url, timeout=10)

            # Get document HTML
            ws.send(json.dumps({
                "id": 1,
                "method": "Runtime.evaluate",
                "params": {"expression": "document.body.innerText"}
            }))
            result = json.loads(ws.recv())
            ws.close()

            text = result.get('result', {}).get('result', {}).get('value', '')
            if text:
                return True, text[:5000]  # Truncate
            return False, "Could not get page content"

        except ImportError:
            return False, "websocket-client not installed (pip install websocket-client)"
        except Exception as e:
            return False, str(e)

    def _browser_do(self, url, action="read", js_code=None, wait_seconds=3):
        """
        POWERFUL browser automation - actually DO things in the browser

        Actions:
        - "read": Open URL and return page text
        - "execute": Open URL and run custom JS, return result
        - "click": Open URL and click element (js_code = selector)
        - "fill": Open URL and fill form (js_code = {selector: value, ...})
        """
        import time

        self.log("SYSTEM", f"Browser action: {action} on {url}")

        # Ensure browser is ready
        if not self._get_browser_debug_port():
            self._start_chrome_with_debug()
            time.sleep(2)

        # Open the URL
        self._run_bash(f'open -a "Google Chrome" "{url}"')
        time.sleep(wait_seconds)

        # Find the tab
        tab = self._find_tab_by_url(url.split('/')[2] if '://' in url else url)
        if not tab:
            # Try again with just domain
            domain = url.replace('https://', '').replace('http://', '').split('/')[0]
            tab = self._find_tab_by_url(domain)

        if not tab:
            return False, f"Could not find tab for {url}"

        tab_id = tab.get('id')

        if action == "read":
            # Get page text
            success, content = self._execute_js_in_tab(tab_id, "document.body.innerText")
            if success:
                return True, content[:10000]  # Limit size
            return False, "Could not read page"

        elif action == "execute":
            # Run custom JS
            if js_code:
                return self._execute_js_in_tab(tab_id, js_code)
            return False, "No JS code provided"

        elif action == "click":
            # Click an element
            if js_code:  # js_code is the selector
                click_js = f'document.querySelector("{js_code}").click(); "clicked"'
                return self._execute_js_in_tab(tab_id, click_js)
            return False, "No selector provided"

        elif action == "fill":
            # Fill form fields (js_code is dict of {selector: value})
            if js_code and isinstance(js_code, dict):
                for selector, value in js_code.items():
                    fill_js = f'''
                    var el = document.querySelector("{selector}");
                    if (el) {{ el.value = "{value}"; el.dispatchEvent(new Event("input", {{bubbles: true}})); }}
                    "filled"
                    '''
                    self._execute_js_in_tab(tab_id, fill_js)
                return True, "Form filled"
            return False, "Invalid form data"

        return False, f"Unknown action: {action}"

    def _get_instagram_username_from_browser(self):
        """Actually get Instagram username by opening browser and reading the page"""
        import time
        import re

        self.log("SYSTEM", "Getting Instagram username via browser automation...")

        # Check if debug port is available
        has_debug = self._get_browser_debug_port()

        if has_debug:
            self.log("SYSTEM", "Browser debug port available, using it")
            # Open Instagram in Chrome (which has debug)
            self._run_bash('open -a "Google Chrome" "https://www.instagram.com/"')
        else:
            self.log("SYSTEM", "Starting browser with debug port...")
            self._start_chrome_with_debug()
            self._run_bash('open -a "Google Chrome" "https://www.instagram.com/"')

        time.sleep(3)  # Wait for page load

        # Find the Instagram tab
        tab = self._find_tab_by_url("instagram.com")
        if not tab:
            self.log("ERROR", "Could not find Instagram tab")
            return None

        # Execute JS to get username from the page
        # Instagram shows username in multiple places - try profile link, meta tags, etc.
        js_code = """
        (function() {
            // Try to find username from profile link
            var profileLink = document.querySelector('a[href*="/accounts/edit/"]');
            if (profileLink) {
                var match = document.querySelector('span[dir="auto"]');
                if (match) return match.textContent;
            }

            // Try from navigation profile link
            var navProfile = document.querySelector('a[href^="/"][role="link"] span');
            if (navProfile && navProfile.textContent && !navProfile.textContent.includes(' ')) {
                return navProfile.textContent;
            }

            // Try from URL if on profile page
            var url = window.location.pathname;
            var match = url.match(/^\\/([a-zA-Z0-9_.]+)\\/?$/);
            if (match) return match[1];

            // Try meta tag
            var meta = document.querySelector('meta[property="al:ios:url"]');
            if (meta) {
                var content = meta.getAttribute('content');
                var match = content.match(/user\\?username=([^&]+)/);
                if (match) return match[1];
            }

            // Last resort - look for Settings link and nearby text
            var settingsLink = document.querySelector('a[href="/accounts/edit/"]');
            if (settingsLink) {
                var parent = settingsLink.closest('div');
                if (parent) {
                    var spans = parent.querySelectorAll('span');
                    for (var i = 0; i < spans.length; i++) {
                        var text = spans[i].textContent;
                        if (text && text.length < 30 && !text.includes(' ') && text.length > 2) {
                            return text;
                        }
                    }
                }
            }

            return null;
        })()
        """

        try:
            success, result = self._execute_js_in_tab(tab.get('id'), js_code)
            if success and result and result != 'null' and result != 'None':
                username = str(result).strip()
                if username and len(username) < 50 and not ' ' in username:
                    self.log("OK", f"Found Instagram username: @{username}")
                    return username
        except Exception as e:
            self.log("ERROR", f"JS execution failed: {e}")

        # Fallback: Try to get page content and parse it
        try:
            success, content = self._get_page_content()
            if success and content:
                # Look for username patterns in page text
                # Instagram pages often have "username's profile" or similar
                matches = re.findall(r'@([a-zA-Z0-9_.]{3,30})', content)
                if matches:
                    # Filter out common non-usernames
                    for m in matches:
                        if m.lower() not in ['instagram', 'facebook', 'meta', 'about', 'help']:
                            self.log("OK", f"Found Instagram username from page: @{m}")
                            return m
        except Exception as e:
            self.log("ERROR", f"Page content parsing failed: {e}")

        return None

    def _execute_js_in_tab(self, tab_id, js_code):
        """Execute JavaScript in a browser tab"""
        try:
            success, tabs = self._get_chrome_tabs()
            if not success:
                return False, "Cannot connect to browser"

            tab = next((t for t in tabs if t.get('id') == tab_id), None)
            if not tab:
                return False, "Tab not found"

            ws_url = tab.get('webSocketDebuggerUrl')
            if not ws_url:
                return False, "No websocket URL"

            import websocket
            ws = websocket.create_connection(ws_url, timeout=10)
            ws.send(json.dumps({
                "id": 1,
                "method": "Runtime.evaluate",
                "params": {"expression": js_code}
            }))
            result = json.loads(ws.recv())
            ws.close()

            return True, result.get('result', {}).get('result', {}).get('value', 'OK')
        except Exception as e:
            return False, str(e)

    def _click_element(self, tab_id, selector):
        """Click an element in the browser"""
        js = f"document.querySelector('{selector}')?.click(); 'clicked'"
        return self._execute_js_in_tab(tab_id, js)

    def _type_text(self, tab_id, selector, text):
        """Type text into an input field"""
        # Escape the text for JS
        escaped_text = text.replace("'", "\\'").replace("\n", "\\n")
        js = f"""
        const el = document.querySelector('{selector}');
        if (el) {{
            el.focus();
            el.value = '{escaped_text}';
            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
            'typed'
        }} else {{
            'element not found'
        }}
        """
        return self._execute_js_in_tab(tab_id, js)

    def _send_instagram_dm(self, request):
        """Send an Instagram DM - ELITE automation with actual page interaction"""
        self.log("SYSTEM", "📱 Instagram DM automation starting...")

        # Parse the request to extract recipient and message
        text = request.lower()
        original_text = request  # Keep original for message extraction

        # Try to extract recipient name (after "to" or before the message)
        recipient = None
        message = None

        # More robust patterns for parsing
        import re

        # Pattern: "send dm to [person] saying/with [message]"
        # Or: "instagram dm [person] [message]"
        # Or: "message [person] on instagram [message]"
        patterns = [
            r'(?:send|dm|message)\s+(?:to\s+)?@?(\w+)\s+(?:saying|with|:)?\s*["\']?(.+?)["\']?$',
            r'(?:instagram|ig)\s+(?:dm|message)\s+(?:to\s+)?@?(\w+)\s*["\']?(.+?)["\']?$',
            r'(?:send|message)\s+["\']?(.+?)["\']?\s+to\s+@?(\w+)(?:\s+on\s+instagram)?',
            r'(?:dm|message)\s+@?(\w+)\s+["\']?(.+?)["\']?$',
            r'(?:text|send to)\s+@?(\w+)\s+["\']?(.+?)["\']?$',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                groups = match.groups()
                # Check which group is the username (shorter, no spaces typically)
                if len(groups) >= 2:
                    g1, g2 = groups[0], groups[1]
                    # Username is usually shorter and has no spaces
                    if ' ' in g1 and ' ' not in g2:
                        recipient, message = g2, g1
                    else:
                        recipient, message = g1, g2
                else:
                    recipient = groups[0]
                break

        # If still no recipient, try simpler extraction
        if not recipient:
            # Look for @username or just a single word after key phrases
            username_match = re.search(r'@(\w+)', text)
            if username_match:
                recipient = username_match.group(1)
            else:
                # Try to find username after common patterns
                for phrase in ['dm ', 'message ', 'to ', 'send ']:
                    if phrase in text:
                        after = text.split(phrase)[-1].split()[0] if text.split(phrase)[-1].split() else None
                        if after and after not in ['on', 'instagram', 'ig', 'saying', 'with']:
                            recipient = after.strip('@')
                            break

        if not recipient:
            return "🤔 Who should I send the message to? Try: 'dm @username your message' or 'send dm to username saying hello'"

        # Clean up recipient
        recipient = recipient.strip('@').strip()

        self.log("SYSTEM", f"Recipient: {recipient}, Message: {message}")

        # Step 1: Open Instagram DMs in Comet
        dm_url = "https://www.instagram.com/direct/inbox/"
        self.log("SYSTEM", f"Opening Instagram DMs in Comet...")
        success, result = self._open_in_comet(dm_url)

        if not success:
            return f"✗ Could not open Instagram: {result}"

        # Give it time to load
        time.sleep(2)

        # Step 2: Check if we can interact via DevTools
        if not self._get_browser_debug_port():
            return f"""✓ **Opened Instagram DMs in Comet**

📱 **To send your message to {recipient}:**
1. Search for **@{recipient}** in the search box
2. Click on their conversation
3. Type: {message or '[your message]'}
4. Press Enter to send

💡 *For full automation, start Comet with:*
   `/Applications/Comet.app/Contents/MacOS/Comet --remote-debugging-port=9222`"""

        # Try to interact with the page
        success, tabs = self._get_chrome_tabs()
        if not success:
            return f"Opened Instagram but can't interact: {tabs}"

        # Find Instagram tab
        ig_tab = None
        for tab in tabs:
            if 'instagram.com' in tab.get('url', ''):
                ig_tab = tab
                break

        if not ig_tab:
            return f"""✓ **Opened Instagram DMs**

📱 Find **@{recipient}** and send: {message or '[your message]'}"""

        # ELITE: Try to actually interact with the page
        tab_id = ig_tab['id']
        self.log("SYSTEM", f"Found Instagram tab, attempting interaction...")

        # Try to search for the user
        search_js = f'''
        (function() {{
            // Try to find and click the search/compose button
            const searchBtn = document.querySelector('[aria-label="New message"]') ||
                             document.querySelector('svg[aria-label="New message"]')?.closest('div[role="button"]') ||
                             document.querySelector('[data-testid="new-message-button"]');
            if (searchBtn) {{
                searchBtn.click();
                return 'clicked_new_message';
            }}

            // Try to find search input directly
            const searchInput = document.querySelector('input[placeholder*="Search"]') ||
                               document.querySelector('input[name="queryBox"]');
            if (searchInput) {{
                searchInput.focus();
                searchInput.value = '{recipient}';
                searchInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
                return 'typed_in_search';
            }}

            return 'no_search_found';
        }})()
        '''

        search_result = self._execute_js_in_tab(tab_id, search_js)
        self.log("SYSTEM", f"Search attempt: {search_result}")

        # If we have a message to send, prepare it
        message_status = ""
        if message:
            message_status = f"\n📝 **Message ready:** {message}"

        # Get page status
        content_success, content = self._get_page_content(tab_id)

        return f"""✓ **Instagram DM Automation Active**

📱 **Target:** @{recipient}{message_status}

**Status:** {'Page loaded and interactive' if search_result[0] else 'Page loaded - manual interaction needed'}
{'✓ ' + str(search_result[1]) if search_result[0] else ''}

**Next steps:**
1. Search for @{recipient} (click the pencil/new message icon)
2. Select their profile from results
3. {'Type and send your message' if not message else f'Send: "{message}"'}

💡 Instagram's modern UI requires manual clicking for security - the page is ready for you!"""

    def _smart_browser_action(self, request):
        """Smart browser action - uses Comet browser with saved sessions"""
        self.log("SYSTEM", "🌐 Smart browser action (using Comet)...")
        text = request.lower()

        # FIRST: Check if this is a specific task we know how to do
        if 'instagram' in text and ('dm' in text or 'message' in text or 'send' in text):
            return self._send_instagram_dm(request)

        # Use REAL URLs from knowledge base
        site_info = {
            'zhipu': {'url': 'https://z.ai', 'api_page': '/manage-apikey/apikey-list'},
            'zhipuai': {'url': 'https://z.ai', 'api_page': '/manage-apikey/apikey-list'},
            'glm': {'url': 'https://z.ai', 'api_page': '/manage-apikey/apikey-list'},
            'glm api': {'url': 'https://z.ai', 'api_page': '/manage-apikey/apikey-list'},
            'glm chat': {'url': 'https://z.ai', 'api_page': '/chat'},
            'z.ai': {'url': 'https://z.ai', 'api_page': '/chat'},
            'bigmodel': {'url': 'https://z.ai', 'api_page': '/chat'},
            'openai': {'url': 'https://platform.openai.com', 'api_page': '/api-keys'},
            'anthropic': {'url': 'https://console.anthropic.com', 'api_page': '/settings/keys'},
            'hyperliquid': {'url': 'https://app.hyperliquid.xyz', 'api_page': '/'},
            'polymarket': {'url': 'https://polymarket.com', 'api_page': '/'},
            'instagram': {'url': 'https://www.instagram.com', 'api_page': '/direct/inbox/'},
            'tradingview': {'url': 'https://www.tradingview.com', 'api_page': ''},
            'topstep': {'url': 'https://app.topsteptrader.com', 'api_page': '/dashboard'},
            'gmail': {'url': 'https://mail.google.com', 'api_page': '/mail/u/0/#inbox'},
            'grok': {'url': 'https://grok.com', 'api_page': ''},
        }

        # Detect which site
        target_site = None
        site_name = None
        for site, info in site_info.items():
            if site in text:
                target_site = info
                site_name = site
                self.log("SYSTEM", f"Detected site: {site}")
                break

        # First check if there's a debug port active to check open tabs
        if self._get_browser_debug_port():
            self.log("SYSTEM", "Browser debug active - checking for existing tabs...")

            success, tabs = self._get_chrome_tabs()
            if success and tabs:
                self.log("SYSTEM", f"Found {len(tabs)} open tabs")

                # Look for matching tab
                for tab in tabs:
                    tab_url = tab.get('url', '')
                    tab_title = tab.get('title', '')

                    if target_site and target_site['url'].split('/')[2] in tab_url:
                        self.log("SYSTEM", f"✓ Found matching tab: {tab_title[:40]}")

                        # Activate the tab
                        try:
                            requests.get(f"http://localhost:9222/json/activate/{tab['id']}", timeout=5)
                        except:
                            pass

                        # Try to get page content
                        content_success, content = self._get_page_content(tab['id'])
                        if content_success:
                            return f"✓ Found open tab: **{tab_title}**\n\nPage content:\n```\n{content[:1500]}\n```"
                        else:
                            return f"✓ Activated existing tab: **{tab_title}**\n\nURL: {tab_url}"

        # No matching tab - open in Comet browser (has saved sessions)
        if target_site:
            full_url = target_site['url'] + target_site.get('api_page', '')
            self.log("SYSTEM", f"Opening in Comet (saved session): {full_url}")

            success, result = self._open_in_comet(full_url)
            if success:
                return f"✓ {result}\n\n💡 Comet browser has your saved sessions - should be logged in automatically!"
            else:
                return f"✗ Failed to open browser: {result}"

        return "🤔 Not sure which site you mean. Try: 'go to zhipu' or 'open glm api page'"

    def _fetch_web_content(self, url):
        """Fetch content from a URL - tries Chrome first, then requests"""
        self.log("SYSTEM", f"Fetching web content: {url[:50]}...")

        # Clean URL
        if not url.startswith('http'):
            url = 'https://' + url

        # First check if this URL is already open in Chrome
        if self._get_chrome_debug_port():
            domain = url.split('/')[2] if '/' in url else url
            tab = self._find_tab_by_url(domain)
            if tab:
                self.log("SYSTEM", f"Found open tab for {domain}")
                success, content = self._get_page_content(tab['id'])
                if success:
                    return True, content

        # Fall back to requests
        try:
            response = requests.get(url, timeout=10, headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            })
            response.raise_for_status()

            content = response.text
            # Truncate if too long
            if len(content) > 5000:
                content = content[:5000] + f"\n\n... (truncated, {len(response.text)} total chars)"

            self.log("OK", f"Fetched {len(response.text)} chars from {url[:30]}")
            return True, content
        except Exception as e:
            self.log("ERROR", f"Web fetch failed: {e}")
            return False, str(e)

    def _open_browser_to_url(self, url):
        """Open browser and navigate to URL - Uses Comet for saved sessions"""
        self.log("SYSTEM", f"Opening browser to: {url}")
        try:
            if not url.startswith('http'):
                url = 'https://' + url

            # Check if debug is running and has this tab already
            if self._get_browser_debug_port():
                domain = url.split('/')[2] if '/' in url[8:] else url.replace('https://', '').replace('http://', '')
                tab = self._find_tab_by_url(domain)
                if tab:
                    self.log("SYSTEM", f"Found existing tab, activating...")
                    try:
                        requests.get(f"http://localhost:9222/json/activate/{tab['id']}", timeout=5)
                        return True, f"Activated existing tab: {tab.get('title', url)}"
                    except:
                        pass

            # Open in Comet browser (has saved sessions)
            return self._open_in_comet(url)
        except Exception as e:
            return False, str(e)

    def _interpret_unknown_action(self, action, details):
        """Try to interpret and execute an unknown action"""
        action_upper = action.upper()

        # Common misspellings/alternatives
        action_map = {
            'RUN': 'BASH',
            'EXEC': 'BASH',
            'EXECUTE': 'BASH',
            'SHELL': 'BASH',
            'CMD': 'BASH',
            'CAT': 'READ',
            'VIEW': 'READ',
            'SHOW': 'READ',
            'GET': 'READ',
            'FETCH': 'WEB',
            'DOWNLOAD': 'WEB',
            'CURL': 'BASH',
            'LAUNCH': 'OPEN',
            'START': 'OPEN',
            'NAVIGATE': 'BROWSE',
            'GOTO': 'BROWSE',
            'GO': 'BROWSE',
            'VISIT': 'BROWSE',
            'BROWSER': 'BROWSE',
            'SAVE': 'WRITE',
            'CREATE': 'WRITE',
            'MAKE': 'WRITE',
        }

        if action_upper in action_map:
            mapped_action = action_map[action_upper]
            self.log("SYSTEM", f"Interpreted '{action}' as '{mapped_action}'")
            return self._execute_step_smart(mapped_action, details)

        # If it looks like a URL, treat as BROWSE
        if '.' in action and '/' not in action:
            # Might be a domain
            return self._open_browser_to_url(action + ' ' + details)

        # Unknown action - return error, don't execute as bash (security fix)
        self.log("SYSTEM", f"Unknown action '{action}' - skipping (not a valid command)")
        return False, f"Unknown action: {action}. Valid actions are: BASH, READ, WRITE, CODE, OPEN, DONE, VERIFY, BROWSE"

    def _parse_plan(self, plan_text):
        """Parse Claude's plan into steps - handles multiple formats"""
        steps = []
        # Whitelist of valid actions - prevents unknown actions from being parsed
        VALID_ACTIONS = ['BASH', 'READ', 'WRITE', 'CODE', 'OPEN', 'DONE', 'VERIFY', 'BROWSE']

        for line in plan_text.split('\n'):
            line = line.strip()

            # Format 1: STEP N: ACTION: details
            if line.upper().startswith('STEP'):
                match = re.match(r'STEP\s*\d+[:\s]+(\w+)[:\s]+(.+)', line, re.IGNORECASE)
                if match and match.group(1).upper() in VALID_ACTIONS:
                    steps.append({
                        'action': match.group(1).upper(),
                        'details': match.group(2).strip()
                    })
                    continue

            # Format 2: N. ACTION: details
            match = re.match(r'\d+\.\s*(\w+)[:\s]+(.+)', line)
            if match and match.group(1).upper() in VALID_ACTIONS:
                steps.append({
                    'action': match.group(1).upper(),
                    'details': match.group(2).strip()
                })
                continue

            # Format 3: - ACTION: details
            match = re.match(r'[-*]\s*(\w+)[:\s]+(.+)', line)
            if match and match.group(1).upper() in VALID_ACTIONS:
                steps.append({
                    'action': match.group(1).upper(),
                    'details': match.group(2).strip()
                })
                continue

            # Format 4: ACTION: details (standalone)
            for action in VALID_ACTIONS:
                if line.upper().startswith(action + ':') or line.upper().startswith(action + ' '):
                    details = line[len(action):].strip().lstrip(':').strip()
                    if details:
                        steps.append({
                            'action': action,
                            'details': details
                        })
                    break

        return steps

    def _generate_code(self, language, description):
        """Generate code using Claude (it's good at this)"""
        try:
            response = self.claude.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2000,
                messages=[{
                    "role": "user",
                    "content": f"Generate {language} code for: {description}\n\nOutput ONLY the code, no explanations."
                }]
            )
            code = response.content[0].text.strip()
            # Remove markdown code blocks if present
            if code.startswith('```'):
                code = '\n'.join(code.split('\n')[1:-1])
            return code
        except:
            return None

    # =========================================================================
    # PROFILE & STATS
    # =========================================================================

    def _show_profile_stats(self):
        """Show profile stats and learning metrics"""
        if self.profile_updater:
            stats = self.profile_updater.get_stats_summary()
            return f"📊 **Profile Stats**\n\n{stats}"
        else:
            costs = self.memory["costs"]
            return f"""📊 **Session Stats**

**Costs:**
- Session: ${costs['session']:.4f}
- GLM: ${costs['glm']:.4f}
- Claude: ${costs['claude']:.4f}
- Total All Time: ${costs['total']:.4f}

**Memory:**
- Learned Intents: {len(self.memory.get('learned_intents', {}))}
- History Items: {len(self.memory.get('history', []))}

(ProfileUpdater not available for full stats)"""

    def _show_profile_summary(self):
        """Show a quick summary of who the user is"""
        if self.profile_updater:
            profile = self.profile_updater.get_profile()
            if profile:
                # Extract key sections
                lines = profile.split('\n')
                summary_parts = []

                # Get identity section
                in_identity = False
                for line in lines[:50]:
                    if '## IDENTITY' in line:
                        in_identity = True
                        continue
                    if in_identity and line.startswith('##'):
                        break
                    if in_identity and line.strip():
                        summary_parts.append(line)

                if summary_parts:
                    return "👤 **Who You Are:**\n\n" + '\n'.join(summary_parts[:10])

        return "👤 Profile not loaded. Run some commands and I'll learn about you!"

    # =========================================================================
    # LOGGING & UTILITIES
    # =========================================================================

    def log(self, source, message, cost=0):
        timestamp = time.strftime("%H:%M:%S")
        colors = {
            "GLM": "\033[92m", "CLAUDE": "\033[94m", "ROUTER": "\033[93m",
            "SYSTEM": "\033[95m", "BASH": "\033[96m", "ERROR": "\033[91m",
            "OK": "\033[92m", "PLAN": "\033[93m", "VERIFY": "\033[96m",
        }
        reset = "\033[0m"
        c = colors.get(source, "")
        cost_str = f" \033[90m[${cost:.4f}]\033[0m" if cost > 0 else ""
        print(f"\033[90m{timestamp}\033[0m [{c}{source:6}{reset}] {message}{cost_str}")

    def _calc_cost(self, model, input_tokens, output_tokens):
        p = self.pricing[model]
        cost = (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000
        self.memory["costs"]["session"] += cost
        self.memory["costs"][model if model == "glm" else "claude"] += cost
        return cost

    def _add_to_history(self, action, result):
        self.memory["history"].append({
            "time": time.strftime("%H:%M"),
            "action": action,
            "result": str(result)[:200]
        })
        self.memory["history"] = self.memory["history"][-15:]

    def _get_context(self):
        if not self.memory["history"]:
            return ""
        recent = self.memory["history"][-5:]
        return "Recent actions:\n" + "\n".join(
            f"- {h['time']}: {h['action']} → {h['result'][:50]}" for h in recent
        )

    # =========================================================================
    # SMART CAPABILITIES - FIGURE THINGS OUT
    # =========================================================================

    def _smart_fallback(self, query, error=""):
        """When something fails, try to figure it out ourselves"""
        self.log("SYSTEM", "Smart fallback - trying to figure it out...")
        query_lower = query.lower()

        # API Key requests - check env files
        if any(x in query_lower for x in ['api key', 'api_key', 'apikey', 'glm key', 'claude key', 'openai key']):
            return self._get_api_key_info(query_lower)

        # Browser/login requests
        if any(x in query_lower for x in ['browser', 'login', 'session', 'chrome', 'sign in']):
            return self._handle_browser_request(query_lower)

        # File/config requests
        if any(x in query_lower for x in ['.env', 'config', 'settings', 'credentials']):
            return self._read_config_info(query_lower)

        # System info requests
        if any(x in query_lower for x in ['system', 'mac', 'memory', 'disk', 'cpu']):
            return self._get_system_info()

        # Project info requests
        if any(x in query_lower for x in ['project', 'supequant', 'clawdbot', 'reddit', 'agent']):
            return self._get_project_info(query_lower)

        # If GLM timed out, return a helpful message
        if 'timeout' in error.lower():
            return "GLM timed out. Let me try to help directly - what do you need? (Try being more specific)"

        return f"I couldn't figure that out automatically. Error: {error}\n\nTry asking more specifically, or use commands like:\n- `run <bash command>`\n- `read <file path>`\n- `open <app or url>`"

    def _get_api_key_info(self, query):
        """Get API key information from env files - ACTUALLY READS AND RETURNS REAL DATA"""
        self.log("SYSTEM", f"Checking API keys for query: '{query}'")

        env_files = [
            "/Users/shamil/clawdbot-v2/.env",  # Primary location
            os.path.expanduser("~/.env"),
            "/Users/shamil/supequant/.env",
            "/Users/shamil/social_agent_codex-1/.env",
        ]

        keys_found = {}
        for env_file in env_files:
            if os.path.exists(env_file):
                try:
                    with open(env_file, 'r') as f:
                        content = f.read()
                        for line in content.split('\n'):
                            if '=' in line and not line.startswith('#'):
                                key, value = line.split('=', 1)
                                key = key.strip()
                                value = value.strip().strip('"').strip("'")
                                if value and ('KEY' in key.upper() or 'TOKEN' in key.upper() or 'SECRET' in key.upper()):
                                    keys_found[key] = {"file": env_file, "full": value}
                except Exception as e:
                    self.log("ERROR", f"Failed to read {env_file}: {e}")

        query_lower = query.lower()

        # Check what specific key they want
        if 'glm' in query_lower or 'zhipu' in query_lower or 'z ai' in query_lower or 'z.ai' in query_lower:
            for key, data in keys_found.items():
                if 'glm' in key.lower():
                    return f"""✓ **GLM API Key:**
```
{data['full']}
```
📍 From: {data['file']}
🌐 Dashboard: https://z.ai/manage-apikey/apikey-list"""
            return "❌ No GLM_API_KEY found in your .env files.\n\n💡 Get one at: https://z.ai/manage-apikey/apikey-list"

        if 'claude' in query_lower or 'anthropic' in query_lower:
            for key, data in keys_found.items():
                if 'claude' in key.lower() or 'anthropic' in key.lower():
                    return f"""✓ **Claude API Key:**
```
{data['full']}
```
📍 From: {data['file']}
🌐 Dashboard: https://console.anthropic.com/settings/keys"""
            return "❌ No CLAUDE_API_KEY found in your .env files.\n\n💡 Get one at: https://console.anthropic.com/settings/keys"

        if 'openai' in query_lower or 'chatgpt' in query_lower or 'gpt' in query_lower:
            for key, data in keys_found.items():
                if 'openai' in key.lower() or 'gpt' in key.lower():
                    return f"""✓ **OpenAI API Key:**
```
{data['full']}
```
📍 From: {data['file']}
🌐 Dashboard: https://platform.openai.com/api-keys"""
            # NOT FOUND - tell them clearly!
            return f"""❌ **No OpenAI/ChatGPT API key found** in your .env files.

📁 Checked: {', '.join(env_files[:2])}

**Your available API keys:**
{chr(10).join([f"  • {k}" for k in keys_found.keys()]) if keys_found else "  (none)"}

💡 Get an OpenAI key at: https://platform.openai.com/api-keys
   Then add `OPENAI_API_KEY=sk-...` to your .env file"""

        if 'telegram' in query_lower:
            for key, data in keys_found.items():
                if 'telegram' in key.lower():
                    return f"""✓ **Telegram Token:**
```
{data['full']}
```
📍 From: {data['file']}"""
            return "❌ No TELEGRAM_TOKEN found in your .env files."

        # Show ALL keys
        if not keys_found:
            return "❌ No API keys found in any .env files."

        result = "**All API Keys Found:**\n\n"
        for key, data in keys_found.items():
            result += f"**{key}:**\n```\n{data['full']}\n```\n📍 {data['file']}\n\n"
        return result.strip()

    def _get_account_info(self, query):
        """Get account/username info - ACTUALLY TRIES TO FIND IT"""
        self.log("SYSTEM", f"Looking up account info for: '{query}'")
        query_lower = query.lower()

        # Instagram
        if 'instagram' in query_lower or ' ig ' in query_lower or query_lower.startswith('ig ') or 'my ig' in query_lower:
            # First check if we learned the username
            learned_username = self.memory.get("instagram_username")
            if learned_username:
                return f"""📸 **Your Instagram Account:**

**Username:** @{learned_username}
**User ID:** {ACCOUNTS.get('instagram', {}).get('user_id', 'unknown') if KNOWLEDGE_LOADED else 'unknown'}

🔗 https://www.instagram.com/{learned_username}"""

            # Try to get username from Instagram Graph API using the access token
            try:
                with open('/Users/shamil/social_agent_codex-1/.env', 'r') as f:
                    content = f.read()
                    access_token = None
                    user_id = None
                    for line in content.split('\n'):
                        if 'IG_ACCESS_TOKEN=' in line:
                            access_token = line.split('=', 1)[1].strip()
                        if 'IG_USER_ID=' in line:
                            user_id = line.split('=', 1)[1].strip()

                    if access_token and user_id:
                        self.log("SYSTEM", "Trying Instagram Graph API to get username...")
                        import requests
                        url = f"https://graph.instagram.com/{user_id}?fields=username&access_token={access_token}"
                        response = requests.get(url, timeout=10)
                        if response.status_code == 200:
                            data = response.json()
                            username = data.get('username')
                            if username:
                                # Save it for next time
                                self.memory["instagram_username"] = username
                                self._save_memory()
                                return f"""📸 **Your Instagram Account:**

**Username:** @{username}
**User ID:** {user_id}

🔗 https://www.instagram.com/{username}"""
            except Exception as e:
                self.log("SYSTEM", f"Instagram API failed: {e}")

            # If API failed, try opening Instagram to check
            self.log("SYSTEM", "Opening Instagram to find your account...")
            success, result = self._open_in_comet("https://www.instagram.com/")

            return f"""📸 **Finding your Instagram...**

✓ Opened Instagram in Comet browser
🔍 Check the profile icon in the top right to see your username

Once you see it, tell me: "my instagram is @yourusername"
And I'll remember it!"""
            return "❌ Instagram account info not found. Check /Users/shamil/social_agent_codex-1/.env"

        # Topstep
        if 'topstep' in query_lower:
            if KNOWLEDGE_LOADED and ACCOUNTS.get('topstep'):
                return f"""📈 **Your Topstep Account:**

**Username:** {ACCOUNTS['topstep'].get('username', 'unknown')}

🔗 https://app.topsteptrader.com/dashboard"""
            return "❌ Topstep account info not found"

        # Email
        if 'email' in query_lower:
            if KNOWLEDGE_LOADED and ACCOUNTS:
                return f"""📧 **Your Email Accounts:**

**Primary:** {ACCOUNTS.get('email_primary', 'unknown')}
**Secondary:** {ACCOUNTS.get('email_secondary', 'unknown')}
**Other:** {ACCOUNTS.get('email_other', 'N/A')}"""
            return "❌ Email info not found"

        # Generic - show all accounts
        if KNOWLEDGE_LOADED and ACCOUNTS:
            result = "**Your Accounts:**\n\n"
            for service, info in ACCOUNTS.items():
                if isinstance(info, dict):
                    result += f"**{service}:**\n"
                    for k, v in info.items():
                        result += f"  • {k}: {v}\n"
                else:
                    result += f"**{service}:** {info}\n"
            return result

        return "❌ No account info found in knowledge base"

    def _handle_browser_request(self, query):
        """Handle browser/login related requests"""
        self.log("SYSTEM", "Handling browser request...")

        # List available browser profiles
        home = os.path.expanduser("~")
        profiles = []
        for item in os.listdir(home):
            if item.startswith('.chrome') or 'profile' in item.lower():
                full_path = os.path.join(home, item)
                if os.path.isdir(full_path):
                    profiles.append(item)

        if 'open' in query or 'launch' in query or 'start' in query:
            # Try to open Chrome with a profile
            if 'debug' in query:
                self._run_bash('open -a "Google Chrome" --args --remote-debugging-port=9222')
                return "✓ Opened Chrome with remote debugging enabled (port 9222)"
            else:
                self._run_bash('open -a "Google Chrome"')
                return "✓ Opened Chrome"

        if 'list' in query or 'show' in query or profiles:
            result = "**Browser Profiles Found:**\n"
            for p in profiles[:10]:
                result += f"- `{p}`\n"
            result += "\nTo open with a specific profile:\n`run open -a 'Google Chrome' --args --user-data-dir=~/.chrome-debug`"
            return result

        return "I can help with browser stuff. Try:\n- `open chrome` - Open Chrome\n- `browser profiles` - List saved profiles\n- `run open -a 'Google Chrome' --args --remote-debugging-port=9222` - Debug mode"

    def _read_config_info(self, query):
        """Read configuration files"""
        self.log("SYSTEM", "Reading config info...")

        # Find relevant env/config files
        search_paths = [
            "/Users/shamil/clawdbot-v2/.env",
            "/Users/shamil/supequant/.env",
            "/Users/shamil/supequant/config.py",
            "/Users/shamil/social_agent_codex-1/.env",
        ]

        for path in search_paths:
            if os.path.exists(path) and any(x in query for x in [os.path.basename(path), os.path.dirname(path).split('/')[-1]]):
                try:
                    with open(path, 'r') as f:
                        content = f.read()
                    # Mask sensitive values
                    lines = content.split('\n')
                    masked_lines = []
                    for line in lines[:30]:  # First 30 lines
                        if '=' in line and any(x in line.upper() for x in ['KEY', 'TOKEN', 'SECRET', 'PASSWORD']):
                            key, val = line.split('=', 1)
                            val = val.strip()
                            masked = val[:6] + '...' if len(val) > 10 else val
                            masked_lines.append(f"{key}={masked}")
                        else:
                            masked_lines.append(line)
                    return f"**{path}:**\n```\n" + '\n'.join(masked_lines) + "\n```"
                except:
                    pass

        return "Specify which config you want to see:\n- `.env` files\n- `config.py` files\n- Or use `read <path>` for any file"

    def _get_system_info(self):
        """Get system information"""
        self.log("SYSTEM", "Getting system info...")

        info = []

        # Memory
        result = subprocess.run("vm_stat | head -5", shell=True, capture_output=True, text=True)
        if result.stdout:
            info.append(f"**Memory:**\n```\n{result.stdout.strip()}\n```")

        # Disk
        result = subprocess.run("df -h / | tail -1", shell=True, capture_output=True, text=True)
        if result.stdout:
            info.append(f"**Disk:** {result.stdout.strip()}")

        # CPU
        result = subprocess.run("sysctl -n machdep.cpu.brand_string", shell=True, capture_output=True, text=True)
        if result.stdout:
            info.append(f"**CPU:** {result.stdout.strip()}")

        # Uptime
        result = subprocess.run("uptime", shell=True, capture_output=True, text=True)
        if result.stdout:
            info.append(f"**Uptime:** {result.stdout.strip()}")

        return '\n\n'.join(info) if info else "Couldn't get system info"

    def _get_project_info(self, query):
        """Get information about projects"""
        self.log("SYSTEM", "Getting project info...")

        projects = {
            'supequant': '/Users/shamil/supequant',
            'clawdbot': '/Users/shamil/clawdbot-v2',
            'reddit': '/Users/shamil/Desktop/reddit_agent',
            'social': '/Users/shamil/social_agent_codex-1',
            'agent': '/Users/shamil/social_agent_codex-1',
            'instagram': '/Users/shamil/social_agent_codex-1/ig_history_engine',
        }

        for name, path in projects.items():
            if name in query and os.path.exists(path):
                # Get basic info
                result = subprocess.run(f"ls -la {path} | head -15", shell=True, capture_output=True, text=True)

                # Check for context files
                context_files = []
                for ctx in ['CLAUDE.md', 'CONTEXT_PACK.md', 'README.md', '.env']:
                    if os.path.exists(os.path.join(path, ctx)):
                        context_files.append(ctx)

                info = f"**Project: {name}**\nPath: `{path}`\n\n"
                info += f"**Context files:** {', '.join(context_files) if context_files else 'None'}\n\n"
                info += f"**Contents:**\n```\n{result.stdout[:500]}\n```"
                return info

        # List all projects
        result = "**Known Projects:**\n"
        for name, path in projects.items():
            exists = "✓" if os.path.exists(path) else "✗"
            result += f"- {exists} `{name}`: {path}\n"
        return result

    # =========================================================================
    # BASH EXECUTION WITH VERIFICATION
    # =========================================================================

    def _run_bash(self, cmd, timeout=60, verify_cmd=None, retry=0):
        """Run bash command with optional verification and retry"""
        self.log("BASH", f"$ {cmd[:80]}{'...' if len(cmd) > 80 else ''}")

        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=timeout
            )
            output = (result.stdout + result.stderr).strip()

            if result.returncode != 0:
                self.log("ERROR", f"Exit {result.returncode}: {output[:100]}")

                # Retry logic for transient failures
                if retry < 2 and any(x in output.lower() for x in ['timeout', 'temporary', 'retry']):
                    self.log("SYSTEM", f"Retrying ({retry + 1}/2)...")
                    time.sleep(1)
                    return self._run_bash(cmd, timeout, verify_cmd, retry + 1)

                return False, output or f"Exit code {result.returncode}"

            # Verification step
            if verify_cmd:
                self.log("VERIFY", f"Verifying: {verify_cmd[:50]}...")
                check = subprocess.run(verify_cmd, shell=True, capture_output=True, text=True)
                if check.returncode != 0:
                    self.log("ERROR", "Verification failed")
                    return False, "Command ran but verification failed"

            self.log("OK", output[:100] if output else "Done")
            return True, output or "Done"

        except subprocess.TimeoutExpired:
            self.log("ERROR", f"Timeout after {timeout}s")
            return False, f"Command timed out after {timeout}s"
        except Exception as e:
            self.log("ERROR", str(e))
            return False, str(e)

    # =========================================================================
    # FILE OPERATIONS
    # =========================================================================

    def _read_file(self, path):
        """Read a file and return its contents - handles both text and binary"""
        try:
            path = os.path.expanduser(path)

            # Try text first
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                self.log("OK", f"Read {path} ({len(content)} chars)")
                return True, content
            except UnicodeDecodeError:
                # It's binary - try to show useful info
                with open(path, 'rb') as f:
                    binary_content = f.read()

                file_size = len(binary_content)
                # Try to detect file type
                magic_bytes = binary_content[:16].hex()

                # Show hex dump of first part
                hex_preview = ' '.join(f'{b:02x}' for b in binary_content[:64])

                # Try to extract any readable strings
                import re
                strings = re.findall(b'[\\x20-\\x7e]{4,}', binary_content[:2000])
                readable_strings = [s.decode('ascii') for s in strings[:10]]

                content = f"[BINARY FILE - {file_size} bytes]\n"
                content += f"Magic bytes: {magic_bytes}\n"
                content += f"Hex preview: {hex_preview}...\n\n"
                if readable_strings:
                    content += f"Readable strings found:\n" + '\n'.join(f'  - {s}' for s in readable_strings)

                self.log("OK", f"Read binary {path} ({file_size} bytes)")
                return True, content

        except Exception as e:
            self.log("ERROR", f"Failed to read {path}: {e}")
            return False, str(e)

    def _write_file(self, path, content):
        """Write content to a file"""
        try:
            path = os.path.expanduser(path)
            # Create directory if needed
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w') as f:
                f.write(content)
            self.log("OK", f"Wrote {path} ({len(content)} chars)")
            return True, f"Written to {path}"
        except Exception as e:
            self.log("ERROR", f"Failed to write {path}: {e}")
            return False, str(e)

    def _list_dir(self, path=".", pattern=None):
        """List directory contents"""
        try:
            path = os.path.expanduser(path)
            if pattern:
                import glob
                files = glob.glob(os.path.join(path, pattern))
            else:
                files = os.listdir(path)
            return True, files
        except Exception as e:
            return False, str(e)

    # =========================================================================
    # WALLPAPER SYSTEM (Proven working)
    # =========================================================================

    def _verify_image_quality(self, file_path):
        try:
            file_size = os.path.getsize(file_path)
            if file_size < MIN_FILE_SIZE:
                return False, 0, 0, file_size, f"File too small: {file_size//1024}KB"

            with Image.open(file_path) as img:
                width, height = img.size

            if width < MIN_WIDTH or height < MIN_HEIGHT:
                return False, width, height, file_size, f"Resolution too low: {width}x{height}"

            return True, width, height, file_size, "OK"
        except Exception as e:
            return False, 0, 0, 0, str(e)

    def _download_and_verify_image(self, url, dest_path):
        self.log("SYSTEM", f"Downloading: {url[:70]}...")
        try:
            response = requests.get(url, timeout=30, headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'
            }, allow_redirects=True)
            response.raise_for_status()

            content_type = response.headers.get('Content-Type', '')
            if not any(t in content_type for t in ['image/', 'octet-stream']):
                return False, f"Not an image: {content_type}", None

            with open(dest_path, 'wb') as f:
                f.write(response.content)

            success, width, height, file_size, msg = self._verify_image_quality(dest_path)

            if success:
                self.log("OK", f"Downloaded: {width}x{height}, {file_size//1024}KB")
                return True, f"{width}x{height}, {file_size//1024}KB", (width, height)
            else:
                self.log("ERROR", f"Quality check failed: {msg}")
                return False, msg, (width, height) if width > 0 else None

        except Exception as e:
            self.log("ERROR", f"Download failed: {e}")
            return False, str(e), None

    def _search_wallhaven(self, query):
        """Search WallHaven for 4K wallpapers"""
        try:
            search_url = f"https://wallhaven.cc/api/v1/search?q={query}&sorting=relevance&resolutions=3840x2160,2560x1440,1920x1080&purity=100"
            response = requests.get(search_url, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data.get('data') and len(data['data']) > 0:
                wallpaper = data['data'][0]
                direct_url = wallpaper.get('path')
                resolution = wallpaper.get('resolution', 'unknown')
                self.log("SYSTEM", f"WallHaven found: {resolution}")
                return direct_url
            return None
        except Exception as e:
            self.log("ERROR", f"WallHaven failed: {e}")
            return None

    def _set_wallpaper(self, url, source_name="image"):
        """Set wallpaper with full verification"""
        self.log("SYSTEM", f"Setting wallpaper: {source_name}")

        timestamp = int(time.time())
        safe_name = re.sub(r'[^a-zA-Z0-9]', '_', source_name)[:20]
        jpg_path = os.path.expanduser(f"~/Desktop/wallpaper_{safe_name}_{timestamp}.jpg")

        success, msg, dimensions = self._download_and_verify_image(url, jpg_path)
        if not success:
            return False, f"Download failed: {msg}", None

        # Convert to HEIC
        heic_path = jpg_path.replace('.jpg', '.heic')
        self._run_bash(f'sips -s format heic "{jpg_path}" --out "{heic_path}" 2>/dev/null', timeout=30)
        wallpaper_path = heic_path if os.path.exists(heic_path) else jpg_path

        # Set using multiple methods
        self._run_bash(f'wallpaper set "{wallpaper_path}" --screen all')

        if os.path.exists("/tmp/setwallpaper"):
            self._run_bash(f'/tmp/setwallpaper "{wallpaper_path}"')

        applescript = f'''tell application "System Events" to tell every desktop to set picture to "{wallpaper_path}"'''
        self._run_bash(f"osascript -e '{applescript}'")

        self._run_bash("killall Dock", timeout=10)
        time.sleep(2)

        # Cleanup
        if os.path.exists(heic_path) and os.path.exists(jpg_path):
            os.remove(jpg_path)
        self._cleanup_old_wallpapers()

        dim_str = f" ({dimensions[0]}x{dimensions[1]})" if dimensions else ""
        return True, f"Wallpaper set: {source_name}{dim_str}", wallpaper_path

    def _cleanup_old_wallpapers(self):
        try:
            import glob
            desktop = os.path.expanduser("~/Desktop")
            for ext in ['jpg', 'heic']:
                pattern = os.path.join(desktop, f"wallpaper_*_*.{ext}")
                files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
                for old_file in files[3:]:
                    try:
                        os.remove(old_file)
                    except:
                        pass
        except:
            pass

    def _set_macos_wallpaper_settings(self, mode, folder=None):
        """Configure macOS wallpaper settings (shuffle, auto-rotate, etc.)"""
        self.log("SYSTEM", f"Setting macOS wallpaper mode: {mode}")

        if mode == "shuffle" or mode == "auto":
            # Enable wallpaper rotation using macOS built-in folders
            # Default to Desktop Pictures or a specified folder
            if not folder:
                folder = "/System/Library/Desktop Pictures"

            # AppleScript to set wallpaper to rotate through a folder
            script = f'''
            tell application "System Events"
                tell every desktop
                    set picture rotation to 1
                    set random order to true
                    set pictures folder to POSIX file "{folder}"
                    set change interval to 1800
                end tell
            end tell
            '''
            success, output = self._run_bash(f"osascript -e '{script}'")

            if success:
                return f"✓ Wallpaper shuffle enabled - rotating through {folder}"
            else:
                # Try alternate method - open System Settings
                self._run_bash('open "x-apple.systempreferences:com.apple.Wallpaper-Settings.extension"')
                return "✓ Opened Wallpaper Settings - enable 'Auto-Rotate' manually for shuffle mode"

        elif mode == "static":
            # Disable rotation
            script = '''
            tell application "System Events"
                tell every desktop
                    set picture rotation to 0
                end tell
            end tell
            '''
            success, output = self._run_bash(f"osascript -e '{script}'")
            return "✓ Wallpaper rotation disabled"

        return f"✗ Unknown wallpaper mode: {mode}"

    def handle_wallpaper(self, query):
        """Smart wallpaper handler - understands natural language"""
        self.log("ROUTER", f"→ WALLPAPER: '{query}'")
        query_lower = query.lower()

        # Detect macOS wallpaper settings commands
        shuffle_keywords = ['shuffle', 'rotate', 'auto', 'random', 'cycle', 'change automatically', 'auto-rotate']
        if any(kw in query_lower for kw in shuffle_keywords):
            return self._set_macos_wallpaper_settings("shuffle")

        if 'static' in query_lower or 'stop rotating' in query_lower or 'stop shuffle' in query_lower:
            return self._set_macos_wallpaper_settings("static")

        # Open wallpaper settings
        if 'settings' in query_lower or 'preferences' in query_lower or 'options' in query_lower:
            self._run_bash('open "x-apple.systempreferences:com.apple.Wallpaper-Settings.extension"')
            return "✓ Opened Wallpaper Settings"

        # Check presets first (free)
        for key, url in self.preset_wallpapers.items():
            if key in query_lower:
                self.log("SYSTEM", f"Using preset: {key}")
                success, msg, path = self._set_wallpaper(url, key)
                if success:
                    return f"✓ {msg}"

        # Search WallHaven for actual images
        failed_urls = []
        for attempt in range(3):
            search_queries = [query, f"{query} dark", f"{query} art"]

            for sq in search_queries:
                url = self._search_wallhaven(sq)
                if url and url not in failed_urls:
                    self.log("SYSTEM", f"Trying: {url[:60]}...")
                    success, msg, path = self._set_wallpaper(url, query)
                    if success:
                        self.memory["wallpaper_cache"][query_lower] = url
                        return f"✓ {msg}"
                    failed_urls.append(url)

        return f"✗ Could not find high-quality wallpaper for '{query}'"

    # =========================================================================
    # GLM (Cheap) - Simple questions
    # =========================================================================

    def glm_chat(self, message):
        """Use GLM for simple questions (very cheap)"""
        self.log("GLM", f"'{message[:50]}...'")

        context = self._get_context()
        system = f"""You are ClawdBot, an extremely capable Mac assistant.
Be concise, accurate, and helpful. Get things done efficiently.
{context}"""

        try:
            response = self.glm.chat.completions.create(
                model="glm-4-plus",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": message}
                ],
                max_tokens=500,
                timeout=30
            )

            reply = response.choices[0].message.content
            cost = self._calc_cost("glm", response.usage.prompt_tokens, response.usage.completion_tokens)
            self.log("GLM", "Response received", cost)
            self._add_to_history(f"chat: {message[:30]}", reply[:50])
            return reply

        except Exception as e:
            self.log("ERROR", f"GLM failed: {e}")
            # If GLM fails, try to figure it out ourselves
            return self._smart_fallback(message, str(e))

    # =========================================================================
    # CLAUDE (Smart) - Complex tasks with planning
    # =========================================================================

    def _create_plan(self, task):
        """Use Claude to create a plan for complex tasks"""
        self.log("PLAN", f"Planning: {task[:50]}...")

        prompt = f"""You are ClawdBot's planning engine. Your job is to analyze the task and create the most effective plan.

TASK: {task}

FIRST, THINK STEP BY STEP:
1. What is the user actually trying to accomplish?
2. What information do I need to gather first?
3. What are the potential failure points?
4. What's the minimal set of actions to succeed?

AVAILABLE ACTIONS:
- BASH: <command> - Run any shell command (can use pipes, &&, etc.)
- READ: <path> - Read file contents
- WRITE: <path>|||<content> - Write content to file (use ||| as separator)
- CODE: <language>|||<description>|||<filepath> - Generate and save code
- OPEN: <app or url> - Just the URL/app name (e.g., "OPEN: x.com"), system handles browser command
- WALLPAPER: <query> - Set desktop wallpaper (searches automatically)
- WEB: <query> - Search web and return relevant information
- VERIFY: <bash command or check> - Verify previous step worked
- DONE: <summary> - Task complete

CRITICAL RULES:
1. Gather information BEFORE taking action (use READ, BASH ls/cat, etc.)
2. Each step must be atomic and verifiable
3. Use VERIFY after any step that could fail silently
4. For file operations: check if file exists first, verify after write
5. For installs: verify the tool is available after installing
6. BASH commands should handle errors gracefully (use || true if needed)
7. Be SPECIFIC - no placeholder paths or vague commands
8. For CODE steps: provide complete, working code - not pseudocode

OUTPUT FORMAT (one step per line):
STEP 1: <ACTION>: <details>
STEP 2: <ACTION>: <details>
...
STEP N: DONE: <what was accomplished>

Create the most efficient, robust plan. Fewer steps is better, but don't skip verification."""

        try:
            response = self.claude.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}]
            )

            plan_text = response.content[0].text.strip()
            cost = self._calc_cost("sonnet", response.usage.input_tokens, response.usage.output_tokens)
            self.log("PLAN", f"Plan created ({plan_text.count('STEP')} steps)", cost)

            # Parse plan into steps
            steps = []
            for line in plan_text.split('\n'):
                if line.strip().startswith('STEP'):
                    # Extract action and details
                    match = re.match(r'STEP \d+:\s*(\w+):\s*(.+)', line.strip())
                    if match:
                        steps.append({"action": match.group(1), "details": match.group(2)})

            return steps

        except Exception as e:
            self.log("ERROR", f"Planning failed: {e}")
            return None

    def _web_search(self, query):
        """Search the web using DuckDuckGo (no API key needed)"""
        self.log("SYSTEM", f"Web search: {query[:50]}...")
        try:
            # Use DuckDuckGo instant answers API
            url = f"https://api.duckduckgo.com/?q={query}&format=json&no_html=1"
            response = requests.get(url, timeout=10)
            data = response.json()

            results = []
            if data.get('AbstractText'):
                results.append(f"Summary: {data['AbstractText']}")
            if data.get('RelatedTopics'):
                for topic in data['RelatedTopics'][:3]:
                    if isinstance(topic, dict) and topic.get('Text'):
                        results.append(f"- {topic['Text'][:150]}")

            if results:
                return True, "\n".join(results)

            # Fallback: just return that we searched
            return True, f"Searched for '{query}' - no instant answer available. Try a more specific query or use 'open google.com/search?q={query}' for full results."
        except Exception as e:
            return False, f"Search failed: {e}"

    def _generate_code(self, language, description, filepath):
        """Use Claude to generate code"""
        self.log("SYSTEM", f"Generating {language} code: {description[:50]}...")

        prompt = f"""Generate complete, working {language} code for:
{description}

REQUIREMENTS:
1. Code must be complete and runnable (not pseudocode)
2. Include necessary imports/headers
3. Add brief comments for complex logic
4. Handle common errors appropriately
5. Follow {language} best practices and conventions

OUTPUT: Only the code, no explanations or markdown. Start directly with the code."""

        try:
            response = self.claude.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt}]
            )

            code = response.content[0].text.strip()
            cost = self._calc_cost("sonnet", response.usage.input_tokens, response.usage.output_tokens)
            self.log("CLAUDE", f"Code generated ({len(code)} chars)", cost)

            # Remove any markdown code blocks if present
            if code.startswith("```"):
                lines = code.split("\n")
                code = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

            # Write to file
            success, msg = self._write_file(filepath, code)
            if success:
                return True, f"Generated {len(code)} chars of {language} code → {filepath}"
            return False, msg

        except Exception as e:
            return False, f"Code generation failed: {e}"

    def _execute_plan(self, steps):
        """Execute a plan step by step with full capability"""
        results = []
        step_outputs = {}  # Store outputs for reference in later steps

        for i, step in enumerate(steps):
            action = step["action"].upper()
            details = step["details"]

            self.log("SYSTEM", f"Step {i+1}/{len(steps)}: {action}: {details[:50]}...")

            if action == "BASH":
                success, output = self._run_bash(details)
                step_outputs[f"step{i+1}"] = output
                results.append({"step": i+1, "action": action, "success": success, "output": output[:300]})
                if not success and "|| true" not in details:
                    self.log("ERROR", f"Step {i+1} failed, stopping plan")
                    break

            elif action == "READ":
                success, content = self._read_file(details)
                step_outputs[f"step{i+1}"] = content if success else ""
                results.append({"step": i+1, "action": action, "success": success, "output": content[:300] if success else content})

            elif action == "WRITE":
                # Format: path|||content
                if "|||" in details:
                    parts = details.split("|||", 1)
                    path, content = parts[0].strip(), parts[1].strip()
                    success, msg = self._write_file(path, content)
                    results.append({"step": i+1, "action": action, "success": success, "output": msg})
                else:
                    results.append({"step": i+1, "action": action, "success": False, "output": "WRITE requires format: path|||content"})

            elif action == "CODE":
                # Format: language|||description|||filepath
                parts = details.split("|||")
                if len(parts) >= 3:
                    language, description, filepath = parts[0].strip(), parts[1].strip(), parts[2].strip()
                    success, msg = self._generate_code(language, description, filepath)
                    results.append({"step": i+1, "action": action, "success": success, "output": msg})
                else:
                    results.append({"step": i+1, "action": action, "success": False, "output": "CODE requires format: language|||description|||filepath"})

            elif action == "WEB":
                success, output = self._web_search(details)
                step_outputs[f"step{i+1}"] = output
                results.append({"step": i+1, "action": action, "success": success, "output": output[:300]})

            elif action == "OPEN":
                result = self._open_app_or_url(details)
                results.append({"step": i+1, "action": action, "success": "✓" in result, "output": result})

            elif action == "WALLPAPER":
                result = self.handle_wallpaper(details)
                results.append({"step": i+1, "action": action, "success": "✓" in result, "output": result})

            elif action == "VERIFY":
                # Verification - can be a bash command or file check
                if "file exists" in details.lower() or "exists:" in details.lower():
                    path_match = re.search(r'(?:exists:?\s*)?[\'"]?([^\'"]+)[\'"]?', details)
                    if path_match:
                        path = path_match.group(1).strip()
                        exists = os.path.exists(os.path.expanduser(path))
                        results.append({"step": i+1, "action": action, "success": exists, "output": f"File {'exists' if exists else 'NOT found'}: {path}"})
                        if not exists:
                            self.log("ERROR", f"Verification failed: {path} not found")
                            break
                else:
                    success, output = self._run_bash(details)
                    results.append({"step": i+1, "action": action, "success": success, "output": output[:200]})
                    if not success:
                        self.log("ERROR", "Verification failed")
                        break

            elif action == "DONE":
                results.append({"step": i+1, "action": action, "success": True, "output": details})
                break

            else:
                results.append({"step": i+1, "action": action, "success": False, "output": f"Unknown action: {action}"})

        return results

    def claude_complex_task(self, query):
        """Handle complex tasks with planning and execution"""
        self.log("CLAUDE", f"Complex task: '{query[:50]}...'")

        # First, determine if this needs planning or is a simple question
        context = self._get_context()

        # Quick classification - when does something need a plan?
        needs_planning = any(word in query.lower() for word in [
            'create', 'build', 'make', 'write', 'setup', 'install', 'configure',
            'find and', 'search and', 'download and', 'organize', 'clean up',
            'fix', 'debug', 'modify', 'change', 'update', 'refactor',
            'script', 'program', 'code', 'automate', 'generate'
        ])

        # Multi-step tasks need planning
        has_multi_step = any(word in query.lower() for word in [
            ' and ', ' then ', 'after that', 'first', 'finally', 'step'
        ])

        if (needs_planning or has_multi_step) and len(query) > 20:
            # Complex task - use planning
            steps = self._create_plan(query)
            if steps:
                self.log("SYSTEM", f"Executing {len(steps)}-step plan...")
                results = self._execute_plan(steps)

                # Summarize results
                successes = sum(1 for r in results if r['success'])
                total = len(results)

                summary = f"Completed {successes}/{total} steps\n"
                for r in results:
                    status = "✓" if r['success'] else "✗"
                    summary += f"  {status} Step {r['step']}: {r['action']} - {r['output'][:60]}\n"

                self._add_to_history(f"plan: {query[:20]}", f"{successes}/{total} steps")
                return summary.strip()

        # Direct response mode - for questions or simple actions
        prompt = f"""You are ClawdBot, an extremely capable Mac assistant running on macOS.

THINK STEP BY STEP before responding:
1. What exactly is the user asking for?
2. Can I answer this directly, or do I need to take an action?
3. If action needed, what's the most efficient way?

CAPABILITIES (actions I can take):
- BASH: <command> - Run any shell command on macOS
- OPEN: <url or app> - Just the URL/app (e.g., "OPEN: x.com"), don't include bash commands
- WALLPAPER: <query> - Search and set desktop wallpaper
- CODE: Generate and save code files
- READ/WRITE: File operations

CONTEXT:
{context}

USER REQUEST: {query}

RESPONSE FORMAT:
- For actions, respond with: ACTION_TYPE: <details>
- For questions, provide a clear, accurate answer
- For explanations, be thorough but concise

Be extremely capable. If you're not sure, reason through it. Don't give up easily."""

        try:
            response = self.claude.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt}]
            )

            result = response.content[0].text.strip()
            cost = self._calc_cost("sonnet", response.usage.input_tokens, response.usage.output_tokens)
            self.log("CLAUDE", "Response received", cost)

            # Handle action responses
            if result.startswith("BASH:"):
                cmd = result[5:].strip()
                success, output = self._run_bash(cmd)
                return f"{'✓' if success else '✗'} {output}"
            elif result.startswith("OPEN:"):
                open_target = result[5:].strip()
                return self._open_app_or_url(open_target)
            elif result.startswith("WALLPAPER:"):
                return self.handle_wallpaper(result[10:].strip())
            else:
                self._add_to_history(f"claude: {query[:30]}", result[:50])
                return result

        except Exception as e:
            self.log("ERROR", f"Claude failed: {e}")
            return f"Claude error: {e}"

    def _open_app_or_url(self, target):
        """Open an app or URL - SMART: tries URL first for known sites"""
        self.log("ROUTER", f"→ DIRECT: open '{target}'")

        # Sanitize target - fix malformed commands where CLI flags leaked into URL
        # e.g., '-a "Comet" "https://x.com"' should become 'https://x.com'
        # Also catches: 'https://-a "Comet" "https://x.com"' (double-wrapped)
        import re
        if target.startswith('-a ') or ' -a ' in target or '-a "' in target:
            # Extract the LAST actual URL from malformed command (in case of doubling)
            url_matches = re.findall(r'https?://[^\s"]+', target)
            if url_matches:
                # Take the last URL (the actual one, not corrupted prefix)
                target = url_matches[-1].rstrip('"')
                self.log("SYSTEM", f"Sanitized malformed target to: {target}")

        target_lower = target.lower()

        # Known websites - use REAL_URLS from shamil_knowledge.py first, then fallback
        known_sites = {
            # AI Services - CORRECT URLs from Shamil's browser history
            'zhipu': 'https://z.ai/manage-apikey/apikey-list',
            'zhipuai': 'https://z.ai/manage-apikey/apikey-list',
            'glm': 'https://z.ai/manage-apikey/apikey-list',
            'glm api': 'https://z.ai/manage-apikey/apikey-list',
            'glm chat': 'https://z.ai/chat',
            'z.ai': 'https://z.ai/chat',
            'bigmodel': 'https://z.ai/chat',
            'zhipu billing': 'https://z.ai/manage-apikey/billing',

            # Trading - Shamil's actual URLs
            'hyperliquid': 'https://app.hyperliquid.xyz',
            'tradingview': 'https://www.tradingview.com',
            'gold': 'https://www.tradingview.com/chart/wOb2l3G9/?symbol=CAPITALCOM%3AGOLD',
            'gold tradingview': 'https://www.tradingview.com/chart/wOb2l3G9/?symbol=CAPITALCOM%3AGOLD',
            'topstep': 'https://app.topsteptrader.com/dashboard',
            'polymarket': 'https://polymarket.com',
            'coinmarketcap': 'https://coinmarketcap.com/converter/',

            # Social Media - with correct subpages
            'instagram': 'https://www.instagram.com/direct/inbox/',
            'instagram dm': 'https://www.instagram.com/direct/inbox/',
            'instagram messages': 'https://www.instagram.com/direct/inbox/',
            'facebook': 'https://www.facebook.com',
            'twitter': 'https://x.com',
            'x': 'https://x.com',
            'grok': 'https://grok.com',

            # Dev Tools
            'github': 'https://github.com',
            'openai': 'https://platform.openai.com/api-keys',
            'anthropic': 'https://console.anthropic.com/settings/keys',
            'claude': 'https://claude.ai',
            'facebook dev': 'https://developers.facebook.com/tools/explorer/',
            'graph api': 'https://developers.facebook.com/tools/explorer/',

            # Email & Communication
            'gmail': 'https://mail.google.com/mail/u/0/#inbox',
            'email': 'https://mail.google.com/mail/u/0/#inbox',
            'telegram': 'https://web.telegram.org',

            # Other
            'youtube': 'https://youtube.com',
            'google': 'https://google.com',
            'reddit': 'https://reddit.com',
            'linkedin': 'https://linkedin.com',
            'stackoverflow': 'https://stackoverflow.com',
            'chatgpt': 'https://chat.openai.com',
        }

        # Override with REAL_URLS from knowledge base if available
        if KNOWLEDGE_LOADED and REAL_URLS:
            known_sites.update(REAL_URLS)

        # Check if it's a known site - use Comet for saved sessions
        if target_lower in known_sites:
            url = known_sites[target_lower]
            success, msg = self._open_in_comet(url)
            result = f"✓ {msg}" if success else f"✗ Failed: {msg}"
            self._add_to_history(f"open {target}", result)
            return result

        # If it has a dot or is a URL, open in Comet
        if "." in target or target.startswith("http"):
            url = target if target.startswith("http") else f"https://{target}"
            success, msg = self._open_in_comet(url)
            result = f"✓ {msg}" if success else f"✗ Failed: {msg}"
            self._add_to_history(f"open {target}", result)
            return result
        else:
            # Try as app first
            success, msg = self._run_bash(f'open -a "{target}"')
            # If app fails, try as website in Comet
            if not success:
                self.log("SYSTEM", f"App not found, trying as website in Comet...")
                url = f"https://{target.lower()}.com"
                success, msg = self._open_in_comet(url)
                if success:
                    result = f"✓ {msg}"
                    self._add_to_history(f"open {target}", result)
                    return result

        result = f"✓ Opened {target}" if success else f"✗ Failed: {msg}"
        self._add_to_history(f"open {target}", result)
        return result

    # =========================================================================
    # SMART ROUTER
    # =========================================================================

    def route(self, user_input):
        """Intelligently route requests to the right handler"""
        text = user_input.lower().strip()

        # === INSTANT ANSWERS (FREE - NO AI) ===
        # Try to answer from SHAMIL_DATA first - most queries can be answered instantly!
        instant = self._try_instant_answer(text)
        if instant:
            self.log("ROUTER", "→ INSTANT: Answered from local data (FREE)")
            return instant

        # === LEARNING: User telling us their username ===
        import re
        learn_patterns = [
            r'my (?:instagram|ig) (?:is|username is|account is|handle is)\s*@?(\w+)',
            r'my (?:instagram|ig):\s*@?(\w+)',
            r'(?:instagram|ig) username[:\s]+@?(\w+)',
        ]
        for pattern in learn_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                username = match.group(1)
                self.log("SYSTEM", f"Learning Instagram username: {username}")
                self.memory["instagram_username"] = username
                self._save_memory()
                return f"✓ Got it! I'll remember your Instagram is **@{username}**"

        # === DIRECT BROWSER ACTIONS (Skip Claude - just do it) ===
        # Instagram username - actually get it from the browser
        if 'instagram' in text and any(x in text for x in ['username', 'user', 'my ig', 'account', 'whats my', "what's my"]):
            if not self.memory.get("instagram_username"):
                self.log("ROUTER", "→ DIRECT: Getting Instagram username via browser")
                username = self._get_instagram_username_from_browser()
                if username:
                    self.memory["instagram_username"] = username
                    self._save_memory()
                    return f"📸 Your Instagram: **@{username}**\nhttps://www.instagram.com/{username}"
                else:
                    # Fallback - just open and ask
                    self._open_in_comet("https://www.instagram.com/")
                    return "📸 Opened Instagram - I couldn't auto-detect your username.\n\nTell me: 'my instagram is @yourusername' and I'll remember it."

        # === SPECIAL COMMANDS ===

        # Show profile stats
        if text in ['profile', 'stats', 'profile stats', 'my profile', 'show stats']:
            return self._show_profile_stats()

        # Show who I am
        if text in ['who am i', 'about me', 'my info']:
            return self._show_profile_summary()

        # === SMART CAPABILITIES (FREE) - Figure things out directly ===

        # === Z.AI / ZHIPU / GLM - Direct handling (user's most common service) ===
        # Normalize text for better matching (remove extra spaces, handle variations)
        text_normalized = ' '.join(text.split())  # collapse multiple spaces

        # Very broad matching for z.ai/zhipu/glm
        is_zai_request = (
            'z ai' in text_normalized or
            'z.ai' in text_normalized or
            'zai' in text_normalized or
            'z-ai' in text_normalized or
            'zhipu' in text_normalized or
            'glm' in text_normalized or
            'bigmodel' in text_normalized or
            ('z' in text_normalized and 'ai' in text_normalized and 'api' in text_normalized)
        )

        if is_zai_request:
            self.log("ROUTER", f"→ SMART: Z.AI/Zhipu service (direct) - matched from: '{text_normalized}'")

            # First, ALWAYS check local .env for the API key
            success, content = self._read_file_smart("/Users/shamil/clawdbot-v2/.env")
            glm_key = None
            if success:
                for line in content.split('\n'):
                    if 'GLM_API_KEY' in line and '=' in line:
                        glm_key = line.split('=', 1)[1].strip().strip('"').strip("'")
                        break

            # Determine what they want
            wants_key = any(x in text_normalized for x in ['key', 'api', 'token', 'credential', 'secret'])
            wants_billing = any(x in text_normalized for x in ['billing', 'usage', 'cost', 'spend', 'money', 'credit'])
            wants_chat = any(x in text_normalized for x in ['chat', 'talk', 'use glm', 'ask glm'])

            if wants_key and glm_key:
                # They want the API key and we have it locally!
                return f"""✓ **Your GLM API Key:**
```
{glm_key}
```

📍 Source: /Users/shamil/clawdbot-v2/.env
🌐 Web dashboard: https://z.ai/manage-apikey/apikey-list"""

            elif wants_billing:
                success, result = self._open_in_comet("https://z.ai/manage-apikey/billing")
                return f"✓ {result}\n\n💰 Billing/usage at https://z.ai/manage-apikey/billing"

            elif wants_chat:
                success, result = self._open_in_comet("https://z.ai/chat")
                return f"✓ {result}\n\n💬 GLM Chat at https://z.ai/chat"

            else:
                # Default: show the API key if we have it, otherwise open the site
                if glm_key:
                    return f"""✓ **Your GLM API Key:**
```
{glm_key}
```

📍 Source: /Users/shamil/clawdbot-v2/.env
🌐 Manage keys: https://z.ai/manage-apikey/apikey-list"""
                else:
                    success, result = self._open_in_comet("https://z.ai/manage-apikey/apikey-list")
                    return f"✓ {result}\n\n🔑 API keys at https://z.ai/manage-apikey/apikey-list"

        # === ACCOUNT/USERNAME QUESTIONS ===
        # Instagram - already handled at top of route(), this is backup
        if 'instagram' in text or 'my ig' in text:
            learned_username = self.memory.get("instagram_username")
            if learned_username:
                self.log("ROUTER", f"→ MEMORY: Instagram username known")
                return f"📸 Your Instagram: **@{learned_username}**\n🔗 https://www.instagram.com/{learned_username}"
            # Don't guess from browser history - that's not YOUR account necessarily
            # Fall through to Claude which will open the browser to check

        # For email - we know this from knowledge base
        if 'my email' in text or 'whats my email' in text:
            self.log("ROUTER", f"→ SMART: Email lookup (free)")
            return f"""📧 **Your Email Accounts:**
**Primary:** ssj4shamil@gmail.com
**Secondary:** noslack111@gmail.com
**Other:** shamilbones1@gmail.com"""

        # For topstep - we know this
        if 'topstep' in text and ('username' in text or 'account' in text or 'my topstep' in text):
            self.log("ROUTER", f"→ SMART: Topstep lookup (free)")
            return f"📈 **Your Topstep:** Username: **Icarus999**\n🔗 https://app.topsteptrader.com/dashboard"

        # Everything else - let Claude figure it out by actually searching!

        # API Key requests - handle directly (FREE) - VERY BROAD MATCHING
        api_key_triggers = ['api key', 'api_key', 'apikey', 'api-key', 'key', 'token', 'credential', 'secret']
        api_services = ['glm', 'claude', 'anthropic', 'openai', 'chatgpt', 'gpt', 'telegram', 'my key', 'my api', 'get key', 'show key', 'all keys', 'keys']
        if any(x in text for x in api_key_triggers) or any(x in text for x in api_services):
            # Check if this is actually an API key request
            if any(x in text for x in ['key', 'api', 'token', 'credential', 'secret']):
                self.log("ROUTER", f"→ SMART: API key lookup (free) - '{text}'")
                return self._get_api_key_info(text)

        # Browser/session requests - handle directly (FREE)
        if any(x in text for x in ['browser profile', 'chrome profile', 'saved session', 'login session']):
            self.log("ROUTER", "→ SMART: Browser info (free)")
            return self._handle_browser_request(text)

        # System info requests - handle directly (FREE)
        if text in ['system info', 'system status', 'my system', 'mac info', 'disk space', 'memory usage']:
            self.log("ROUTER", "→ SMART: System info (free)")
            return self._get_system_info()

        # Project info/status requests - handle directly (FREE)
        if any(x in text for x in ['project info', 'about supequant', 'about clawdbot', 'about reddit', 'project status', 'my projects', 'status of my', 'working on']):
            self.log("ROUTER", "→ SMART: Project info (free)")
            # If asking about status, use profile
            if any(x in text for x in ['status', 'working on', 'progress', 'my projects']):
                return self._get_project_status_from_profile()
            return self._get_project_info(text)

        # Config file requests - handle directly (FREE)
        if any(x in text for x in ['show .env', 'read .env', 'show config', 'my config', 'env file']):
            self.log("ROUTER", "→ SMART: Config info (free)")
            return self._read_config_info(text)

        # === SMART FILE FINDER (FREE) - Find and read files by description ===
        file_keywords = ['file', 'passkey', 'preferences', 'state', 'config', 'settings', 'data']
        action_keywords = ['get', 'read', 'show', 'find', 'cat', 'open']
        if any(x in text for x in action_keywords) and any(x in text for x in file_keywords):
            self.log("ROUTER", "→ SMART: File finder (free)")
            return self._smart_find_and_read(user_input)

        # === INSTAGRAM DM - Direct route for messaging ===
        if 'instagram' in text and any(x in text for x in ['dm', 'message', 'send', 'text']):
            self.log("ROUTER", "→ SMART: Instagram DM automation")
            return self._send_instagram_dm(user_input)

        # === SMART BROWSER/WEB - Uses saved sessions, checks open tabs ===
        web_triggers = ['go to', 'goto', 'navigate', 'visit', 'open site', 'the site', 'website', 'browse to', 'check my', 'get my', 'show my']
        site_keywords = ['zhipu', 'glm', 'z.ai', 'openai', 'anthropic', 'hyperliquid', 'github', 'api key', 'api usage', 'dashboard', 'account', 'tradingview', 'topstep', 'polymarket', 'grok']
        if any(x in text for x in web_triggers) and any(x in text for x in site_keywords):
            self.log("ROUTER", "→ SMART: Browser with saved session")
            return self._smart_browser_action(user_input)

        # Simpler web triggers (just open the site)
        simple_web_triggers = ['go to', 'goto', 'navigate', 'visit', 'open site', 'the site', 'website', 'browse to']
        if any(x in text for x in simple_web_triggers):
            self.log("ROUTER", "→ SMART: Web/browser action")
            return self._smart_web_action(user_input)

        # === TIER 0: Check learned intents first ===
        learned = self.get_learned_intent(text)
        if learned:
            self.log("ROUTER", f"→ LEARNED: {learned['intent']}")
            if learned['intent'] == 'wallpaper_shuffle':
                return self._set_macos_wallpaper_settings("shuffle")
            elif learned['intent'] == 'wallpaper_static':
                return self._set_macos_wallpaper_settings("static")
            elif learned['intent'] == 'wallpaper_settings':
                self._run_bash('open "x-apple.systempreferences:com.apple.Wallpaper-Settings.extension"')
                return "✓ Opened Wallpaper Settings"
            # Add more learned intents as needed

        # === TIER 0.5: Smart intent detection (before keyword matching) ===
        # Detect wallpaper-related commands even without "wallpaper" keyword
        wallpaper_shuffle_phrases = [
            'shuffle all', 'rotate wallpapers', 'auto change background',
            'randomize background', 'change wallpaper automatically',
            'shuffle backgrounds', 'rotate backgrounds', 'shuffle desktop',
            'put it on shuffle', 'enable shuffle', 'turn on shuffle'
        ]
        if any(phrase in text for phrase in wallpaper_shuffle_phrases):
            # Learn this for next time
            self.learn_intent(text, 'wallpaper_shuffle', 'macOS wallpaper rotation')
            return self._set_macos_wallpaper_settings("shuffle")

        # === TIER 1: Direct (Free) ===

        # Tweet - open Twitter with compose
        if 'tweet' in text:
            tweet_match = re.search(r'tweet\s+["\']?(.+?)["\']?\s*$', text, re.IGNORECASE)
            if tweet_match:
                tweet_text = tweet_match.group(1).strip().strip('"\'')
                # URL encode the tweet text
                import urllib.parse
                encoded = urllib.parse.quote(tweet_text)
                url = f"https://x.com/intent/tweet?text={encoded}"
                self._open_in_comet(url)
                return f"🐦 Opened Twitter compose with your tweet:\n\"{tweet_text}\"\n\nJust click 'Post' to send it!"
            else:
                # Just open compose
                self._open_in_comet("https://x.com/compose/tweet")
                return "🐦 Opened Twitter compose - type your tweet and post!"

        # YouTube random video
        if 'youtube' in text and ('random' in text or 'video' in text or 'play' in text):
            # Random topics for variety
            import random
            topics = [
                'lofi hip hop', 'nature documentary', 'space exploration',
                'satisfying videos', 'cooking asmr', 'jazz music',
                'synthwave', 'ambient music', 'cat videos', 'travel vlog',
                'science explained', 'art timelapse', 'ocean waves'
            ]
            topic = random.choice(topics)
            import urllib.parse
            encoded = urllib.parse.quote(topic)
            url = f"https://www.youtube.com/results?search_query={encoded}"
            self._open_in_comet(url)
            return f"🎬 Opened YouTube search for '{topic}' - click any video to play!"

        # Wallpaper
        if "wallpaper" in text:
            match = re.search(r'wallpaper\s+(?:of\s+|to\s+|with\s+)?(.+)', text)
            subject = match.group(1).strip() if match else text.replace("wallpaper", "").strip() or "nature"
            return self.handle_wallpaper(subject)

        # Open app/URL
        if text.startswith("open "):
            return self._open_app_or_url(user_input[5:].strip())

        # Direct bash
        if text.startswith("run ") or text.startswith("$ "):
            cmd = user_input[4:].strip() if text.startswith("run ") else user_input[2:].strip()
            self.log("ROUTER", "→ DIRECT: bash")
            success, output = self._run_bash(cmd)
            result = f"{'✓' if success else '✗'} {output}"
            self._add_to_history(f"bash: {cmd[:30]}", result[:50])
            return result

        # Read file - SMART handling
        if text.startswith("read ") or text.startswith("cat "):
            path_or_desc = user_input.split(maxsplit=1)[1].strip()
            # Check if it's a path or a description
            if path_or_desc.startswith('/') or path_or_desc.startswith('~') or path_or_desc.startswith('.'):
                # It's a path - use smart read
                success, content = self._read_file_smart(path_or_desc)
                return content if success else f"✗ {content}"
            else:
                # It's a description - use collaborative brain to figure it out
                self.log("ROUTER", "→ COLLABORATIVE BRAIN (need to find file)")
                return self._collaborative_process(user_input)

        # Show costs
        if text in ["costs", "cost", "stats", "status"]:
            costs = self.memory["costs"]
            return f"""Session costs:
  GLM:    ${costs['glm']:.4f}
  Claude: ${costs['claude']:.4f}
  Total:  ${costs['session']:.4f}"""

        # Help
        if text in ["help", "?", "commands"]:
            return """ClawdBot v3.2 ELITE - Capabilities:

DIRECT (Free):
  wallpaper <anything>  - Find & set 4K wallpaper
  open <app/url>        - Open apps or websites
  tweet <message>       - Compose a tweet (opens Twitter)
  youtube random video  - Play a random YouTube video
  run <command>         - Execute bash commands
  read <file>           - Read file contents

SMART (Uses AI):
  Any question          - GLM handles simple, Claude handles complex
  "create a script..."  - Plans and executes multi-step tasks
  "fix this code..."    - Analyzes and modifies code
  "search for..."       - Web research

EXAMPLES:
  "tweet Hello world!"
  "youtube random video"
  "wallpaper cyberpunk city"
  "open spotify"
  "create a python script that monitors CPU usage"
  "what's the weather in NYC?"
  "run ls -la ~/Desktop"

Type 'costs' to see spending, 'quit' to exit.
'remember' to see what I've learned."""

        # Show learned intents
        if text in ["remember", "memory", "learned", "what did you learn"]:
            if not self.memory["learned_intents"]:
                return "I haven't learned any custom intents yet. Use me more and I'll learn your preferences!"
            intents = "\n".join(f"  '{k}' → {v['intent']}" for k, v in self.memory["learned_intents"].items())
            return f"🧠 Learned intents:\n{intents}"

        # === COLLABORATIVE BRAIN - GLM & CLAUDE WORK TOGETHER ===
        # Instead of routing to just one, let them collaborate
        self.log("ROUTER", "→ COLLABORATIVE BRAIN")
        return self._collaborative_process(user_input)

    # =========================================================================
    # MAIN LOOP
    # =========================================================================

    def run(self):
        print(f"""
\033[90mType 'help' for commands, or just ask anything!\033[0m
\033[90mSimple questions → GLM (cheap) | Complex tasks → Claude (smart)\033[0m
""")

        while True:
            try:
                user_input = input("\n\033[93m🦞 You:\033[0m ").strip()

                if not user_input:
                    continue

                if user_input.lower() in ['quit', 'exit', 'bye', 'q']:
                    self._end_session()
                    costs = self.memory["costs"]
                    print(f"\n\033[90mSession total: ${costs['session']:.4f}\033[0m")
                    print("\n👋 Later!\n")
                    break

                # Track user message for learning
                self.session_data["user_messages"].append(user_input)
                self.session_data["commands"].append(user_input)

                response = self.route(user_input)
                print(f"\n\033[96m🤖 ClawdBot:\033[0m {response}")

                # Track success/failure based on response
                if "✗" in response or "error" in response.lower() or "failed" in response.lower():
                    self.session_data["failures"].append(user_input)
                    if self.profile_updater:
                        self.profile_updater.add_frustration(f"Command failed: {user_input[:100]}", auto=True)
                elif "✓" in response or "success" in response.lower() or "done" in response.lower():
                    self.session_data["successes"].append(user_input)
                    if self.profile_updater:
                        self.profile_updater.add_win(f"Command succeeded: {user_input[:100]}", auto=True)

                # Save memory periodically
                if len(self.memory["history"]) % 5 == 0:
                    self._save_memory()

            except KeyboardInterrupt:
                self._end_session()
                costs = self.memory["costs"]
                print(f"\n\n\033[90mSession total: ${costs['session']:.4f}\033[0m")
                print("\n👋 Later!\n")
                break
            except Exception as e:
                self.log("ERROR", f"Unexpected error: {e}")
                self.session_data["failures"].append(str(e))
                print(f"\n\033[91m🤖 ClawdBot:\033[0m Something broke: {e}")

    def _end_session(self):
        """End session - save memory and update profile"""
        self._save_memory()

        # Update profile with session insights
        if self.profile_updater:
            try:
                duration = (time.time() - self.session_data["start_time"]) / 60  # minutes
                self.session_data["duration"] = duration
                self.profile_updater.update_after_session(self.session_data)
                self.log("SYSTEM", "Profile updated with session insights")
            except Exception as e:
                self.log("SYSTEM", f"Profile update failed: {e}")

    def get_user_profile(self):
        """Get current user profile for context"""
        if self.profile_updater:
            return self.profile_updater.get_profile()
        return ""

    def track_api_cost(self, provider: str, cost: float):
        """Track API cost in profile"""
        if self.profile_updater:
            self.profile_updater.track_api_cost(provider, cost)


class TelegramBot:
    """Telegram interface for ClawdBot"""

    def __init__(self, clawdbot):
        self.bot = clawdbot
        self.allowed_users = set()  # Empty = allow all, or add user IDs to restrict

    async def start(self, update, context):
        """Handle /start command"""
        user = update.effective_user
        await update.message.reply_text(
            f"🦞 Hey {user.first_name}! I'm ClawdBot.\n\n"
            "I can control your Mac remotely:\n"
            "• Set wallpapers: `wallpaper cyberpunk`\n"
            "• Open apps: `open spotify`\n"
            "• Run commands: `run ls ~/Desktop`\n"
            "• Ask anything!\n\n"
            "Type /help for more commands.",
            parse_mode='Markdown'
        )

    async def help_command(self, update, context):
        """Handle /help command"""
        await update.message.reply_text(
            "🦞 *ClawdBot Commands*\n\n"
            "*Direct (Free):*\n"
            "`wallpaper <query>` - Set 4K wallpaper\n"
            "`open <app/url>` - Open apps/websites\n"
            "`run <command>` - Execute bash\n"
            "`read <file>` - Read file contents\n\n"
            "*Smart (AI):*\n"
            "Just ask anything! Simple questions are cheap (GLM), complex tasks use Claude.\n\n"
            "*Examples:*\n"
            "• `wallpaper sunset mountains`\n"
            "• `open youtube.com`\n"
            "• `create a python script that...`\n"
            "• `what time is it in Tokyo?`\n\n"
            "/costs - Show session costs\n"
            "/screenshot - Take a screenshot",
            parse_mode='Markdown'
        )

    async def costs_command(self, update, context):
        """Handle /costs command"""
        costs = self.bot.memory["costs"]
        await update.message.reply_text(
            f"💰 *Session Costs*\n\n"
            f"GLM: ${costs['glm']:.4f}\n"
            f"Claude: ${costs['claude']:.4f}\n"
            f"*Total: ${costs['session']:.4f}*",
            parse_mode='Markdown'
        )

    async def screenshot_command(self, update, context):
        """Take and send a screenshot"""
        await update.message.reply_text("📸 Taking screenshot...")

        screenshot_path = "/tmp/clawdbot_screenshot.png"
        success, output = self.bot._run_bash(f'screencapture -x "{screenshot_path}"')

        if success and os.path.exists(screenshot_path):
            with open(screenshot_path, 'rb') as photo:
                await update.message.reply_photo(photo=photo, caption="📸 Current screen")
            os.remove(screenshot_path)
        else:
            await update.message.reply_text(f"❌ Screenshot failed: {output}")

    async def handle_message(self, update, context):
        """Handle incoming messages"""
        user_id = update.effective_user.id
        user_name = update.effective_user.first_name

        # Optional: Restrict to allowed users
        if self.allowed_users and user_id not in self.allowed_users:
            await update.message.reply_text("⛔ You're not authorized to use this bot.")
            return

        message = update.message.text
        self.bot.log("TELEGRAM", f"{user_name}: {message[:50]}...")

        # Send "typing" indicator for longer operations
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')

        try:
            # Route through ClawdBot
            response = self.bot.route(message)

            # Split long messages (Telegram has a 4096 char limit)
            if len(response) > 4000:
                chunks = [response[i:i+4000] for i in range(0, len(response), 4000)]
                for chunk in chunks:
                    await update.message.reply_text(f"🤖 {chunk}")
            else:
                await update.message.reply_text(f"🤖 {response}")

            # If wallpaper was set, send a preview
            if "wallpaper set" in response.lower():
                # Find the most recent wallpaper file
                import glob
                desktop = os.path.expanduser("~/Desktop")
                wallpapers = sorted(glob.glob(f"{desktop}/wallpaper_*.heic"), key=os.path.getmtime, reverse=True)
                if wallpapers:
                    # Convert HEIC to JPG for Telegram
                    jpg_path = "/tmp/wallpaper_preview.jpg"
                    self.bot._run_bash(f'sips -s format jpeg "{wallpapers[0]}" --out "{jpg_path}" 2>/dev/null')
                    if os.path.exists(jpg_path):
                        with open(jpg_path, 'rb') as photo:
                            await update.message.reply_photo(photo=photo, caption="🖼️ New wallpaper")
                        os.remove(jpg_path)

        except Exception as e:
            self.bot.log("ERROR", f"Telegram handler error: {e}")
            await update.message.reply_text(f"❌ Error: {e}")

    def run(self):
        """Start the Telegram bot"""
        from telegram import Update
        from telegram.ext import Application, CommandHandler, MessageHandler, filters

        print("\n🦞 Starting ClawdBot Telegram bot...")
        print(f"   Token: {TELEGRAM_TOKEN[:20]}...")

        # Create application
        app = Application.builder().token(TELEGRAM_TOKEN).build()

        # Add handlers
        app.add_handler(CommandHandler("start", self.start))
        app.add_handler(CommandHandler("help", self.help_command))
        app.add_handler(CommandHandler("costs", self.costs_command))
        app.add_handler(CommandHandler("screenshot", self.screenshot_command))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))

        print("   Bot is running! Send a message on Telegram.")
        print("   Press Ctrl+C to stop.\n")

        # Run the bot
        app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    # Handle --profile flag first (before creating bot to show clean output)
    if len(sys.argv) > 1 and sys.argv[1] == "--profile":
        bot = ClawdBot()
        from agents.profiler import ProfilerAgent
        profiler = ProfilerAgent(bot)
        profile = profiler.build_profile()
        if profile:
            print("\n" + "=" * 60)
            print(profile)
        sys.exit(0)

    bot = ClawdBot()

    # Check command line args
    if len(sys.argv) > 1 and sys.argv[1] == "--telegram":
        # Run as Telegram bot
        telegram_bot = TelegramBot(bot)
        telegram_bot.run()
    else:
        # Run as CLI
        bot.run()
