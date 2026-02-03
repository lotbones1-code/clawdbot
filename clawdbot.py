#!/usr/bin/env python3
"""
ClawdBot v3.0 - An extremely capable AI assistant
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

        self.pricing = {
            "glm": {"input": 0.10, "output": 0.10},
            "sonnet": {"input": 3.00, "output": 15.00}
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

        print(self._banner())

    def _banner(self):
        return """
\033[96m╔═══════════════════════════════════════════════════════════════════╗
║                        CLAWDBOT v3.0                              ║
║          "Extremely capable. Figures things out."                 ║
╠═══════════════════════════════════════════════════════════════════╣
║  🆓 DIRECT      │  💰 GLM         │  🧠 CLAUDE                    ║
║  presets, open  │  simple Q&A     │  planning, code, research     ║
║  bash commands  │  chat           │  complex multi-step tasks     ║
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
        """Read a file and return its contents"""
        try:
            path = os.path.expanduser(path)
            with open(path, 'r') as f:
                content = f.read()
            self.log("OK", f"Read {path} ({len(content)} chars)")
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
                model="glm-4-flash",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": message}
                ],
                max_tokens=500
            )

            reply = response.choices[0].message.content
            cost = self._calc_cost("glm", response.usage.prompt_tokens, response.usage.completion_tokens)
            self.log("GLM", "Response received", cost)
            self._add_to_history(f"chat: {message[:30]}", reply[:50])
            return reply

        except Exception as e:
            self.log("ERROR", f"GLM failed: {e}")
            return f"GLM error: {e}"

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
- OPEN: <app or url> - Open application or URL
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
- OPEN: <app or url> - Open applications or URLs
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
                return self._open_app_or_url(result[5:].strip())
            elif result.startswith("WALLPAPER:"):
                return self.handle_wallpaper(result[10:].strip())
            else:
                self._add_to_history(f"claude: {query[:30]}", result[:50])
                return result

        except Exception as e:
            self.log("ERROR", f"Claude failed: {e}")
            return f"Claude error: {e}"

    def _open_app_or_url(self, target):
        """Open an app or URL"""
        self.log("ROUTER", f"→ DIRECT: open '{target}'")

        if "." in target or target.startswith("http"):
            url = target if target.startswith("http") else f"https://{target}"
            success, msg = self._run_bash(f'open "{url}"')
        else:
            success, msg = self._run_bash(f'open -a "{target}"')

        result = f"✓ Opened {target}" if success else f"✗ Failed: {msg}"
        self._add_to_history(f"open {target}", result)
        return result

    # =========================================================================
    # SMART ROUTER
    # =========================================================================

    def route(self, user_input):
        """Intelligently route requests to the right handler"""
        text = user_input.lower().strip()

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

        # Read file
        if text.startswith("read ") or text.startswith("cat "):
            path = user_input.split(maxsplit=1)[1].strip()
            success, content = self._read_file(path)
            return content if success else f"✗ {content}"

        # Show costs
        if text in ["costs", "cost", "stats", "status"]:
            costs = self.memory["costs"]
            return f"""Session costs:
  GLM:    ${costs['glm']:.4f}
  Claude: ${costs['claude']:.4f}
  Total:  ${costs['session']:.4f}"""

        # Help
        if text in ["help", "?", "commands"]:
            return """ClawdBot v3.0 - Capabilities:

DIRECT (Free):
  wallpaper <anything>  - Find & set 4K wallpaper
  open <app/url>        - Open apps or websites
  run <command>         - Execute bash commands
  read <file>           - Read file contents

SMART (Uses AI):
  Any question          - GLM handles simple, Claude handles complex
  "create a script..."  - Plans and executes multi-step tasks
  "fix this code..."    - Analyzes and modifies code
  "search for..."       - Web research

EXAMPLES:
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

        # === TIER 2: GLM (Cheap) - Simple questions ===
        simple_patterns = [
            r'^(what|who|where|when|why|how|is|are|can|do|does|will|would|should)\s',
            r'^(tell|explain|describe|define|list)\s',
            r'\?$',
            r'^(hi|hello|hey|thanks|thank you|ok|okay|cool|nice|great)',
        ]

        is_simple = any(re.match(p, text) for p in simple_patterns)
        is_short = len(text) < 80

        complex_indicators = [
            "find", "search", "look up", "get me", "download", "create", "build",
            "figure out", "help me", "analyze", "compare", "write", "code",
            "debug", "fix", "make", "setup", "install", "configure", "organize"
        ]
        is_complex = any(ind in text for ind in complex_indicators)

        if is_simple and is_short and not is_complex:
            self.log("ROUTER", "→ GLM (simple)")
            return self.glm_chat(user_input)

        # === TIER 3: Claude (Smart) - Complex tasks ===
        self.log("ROUTER", "→ CLAUDE (complex)")
        return self.claude_complex_task(user_input)

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
                    self._save_memory()
                    costs = self.memory["costs"]
                    print(f"\n\033[90mSession total: ${costs['session']:.4f}\033[0m")
                    print("\n👋 Later!\n")
                    break

                response = self.route(user_input)
                print(f"\n\033[96m🤖 ClawdBot:\033[0m {response}")

                # Save memory periodically
                if len(self.memory["history"]) % 5 == 0:
                    self._save_memory()

            except KeyboardInterrupt:
                self._save_memory()
                costs = self.memory["costs"]
                print(f"\n\n\033[90mSession total: ${costs['session']:.4f}\033[0m")
                print("\n👋 Later!\n")
                break
            except Exception as e:
                self.log("ERROR", f"Unexpected error: {e}")
                print(f"\n\033[91m🤖 ClawdBot:\033[0m Something broke: {e}")


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
    bot = ClawdBot()

    # Check command line args
    if len(sys.argv) > 1 and sys.argv[1] == "--telegram":
        # Run as Telegram bot
        telegram_bot = TelegramBot(bot)
        telegram_bot.run()
    else:
        # Run as CLI
        bot.run()
