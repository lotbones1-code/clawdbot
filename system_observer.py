#!/usr/bin/env python3
"""
SystemObserver - Observe and Learn from User's Actual System
============================================================
Instead of guessing how things work, OBSERVE the actual system.

Features:
- Get ALL open browser tabs
- Detect login states by observing UI
- Read iMessage contacts
- Discover installed apps
- Take screenshots of specific sites

This is the foundation for "Learn by Watching" - ClawdBot
can now SEE what the user's system actually looks like.
"""

import os
import json
import sqlite3
import subprocess
import urllib.request
import base64
from datetime import datetime
from typing import Dict, List, Optional, Any

# Try to import browser_cdp for screenshots
try:
    from browser_cdp import BrowserCDP
    CDP_AVAILABLE = True
except ImportError:
    CDP_AVAILABLE = False


class SystemObserver:
    """
    Observe and document the user's actual system.

    This replaces guessing with observing.
    """

    STATE_PATH = os.path.expanduser("~/.clawdbot/system_state.json")
    CDP_URL = "http://localhost:9222"

    def __init__(self):
        self.state = self._load_state()
        self.browser = BrowserCDP() if CDP_AVAILABLE else None

    # =========================================================================
    # STATE PERSISTENCE
    # =========================================================================

    def _load_state(self) -> Dict:
        """Load previously discovered state"""
        if os.path.exists(self.STATE_PATH):
            try:
                with open(self.STATE_PATH, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {
            "discovered_at": None,
            "browser_tabs": [],
            "logged_in_sites": [],
            "contacts": [],
            "apps": []
        }

    def save_state(self):
        """Save discovered state"""
        self.state["last_updated"] = datetime.now().isoformat()
        os.makedirs(os.path.dirname(self.STATE_PATH), exist_ok=True)
        with open(self.STATE_PATH, 'w') as f:
            json.dump(self.state, f, indent=2)
        print(f"✓ Saved system state to {self.STATE_PATH}")

    # =========================================================================
    # BROWSER OBSERVATION
    # =========================================================================

    def get_all_tabs(self) -> List[Dict]:
        """
        Get ALL open tabs in the browser.

        Returns list of:
        {
            "id": "...",
            "url": "https://...",
            "title": "Page Title",
            "domain": "instagram.com",
            "type": "page"
        }
        """
        try:
            # Use CDP to get all targets
            data = urllib.request.urlopen(f"{self.CDP_URL}/json/list", timeout=5).read()
            targets = json.loads(data)

            tabs = []
            for target in targets:
                if target.get("type") == "page":
                    url = target.get("url", "")
                    domain = self._extract_domain(url)

                    tabs.append({
                        "id": target.get("id"),
                        "url": url,
                        "title": target.get("title", ""),
                        "domain": domain,
                        "type": "page"
                    })

            return tabs

        except Exception as e:
            print(f"⚠ Could not get tabs: {e}")
            return []

    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL"""
        if not url:
            return ""
        url = url.replace("https://", "").replace("http://", "")
        return url.split("/")[0].replace("www.", "")

    def discover_browser_state(self) -> Dict:
        """
        Full browser discovery:
        - All open tabs
        - Unique domains
        - Potential login states
        """
        print("🔍 Discovering browser state...")

        tabs = self.get_all_tabs()
        domains = list(set(t["domain"] for t in tabs if t["domain"]))

        # Store in state
        self.state["browser_tabs"] = tabs
        self.state["discovered_at"] = datetime.now().isoformat()

        result = {
            "total_tabs": len(tabs),
            "unique_domains": len(domains),
            "domains": domains,
            "tabs": tabs
        }

        print(f"  Found {len(tabs)} tabs across {len(domains)} domains")
        return result

    def screenshot_tab(self, domain_or_url: str, save_path: str = None) -> Dict:
        """
        Screenshot a specific tab by domain or URL.

        If save_path provided, saves PNG. Always returns base64.
        """
        if not self.browser:
            return {"success": False, "error": "Browser CDP not available"}

        # Connect to the specific domain
        if self.browser.connect(domain_or_url):
            result = self.browser.screenshot_base64()
            result["domain"] = domain_or_url

            if save_path and result.get("image"):
                # Save PNG
                img_data = base64.b64decode(result["image"])
                with open(save_path, 'wb') as f:
                    f.write(img_data)
                result["saved_to"] = save_path

            self.browser.disconnect()
            return result

        return {"success": False, "error": f"Could not connect to {domain_or_url}"}

    def observe_site(self, domain: str) -> Dict:
        """
        Deep observation of a specific site.

        Returns:
        - Screenshot (base64)
        - Page text content
        - Detected login state
        - Current URL and title
        """
        print(f"🔍 Observing {domain}...")

        if not self.browser:
            return {"success": False, "error": "Browser CDP not available"}

        if not self.browser.connect(domain):
            return {"success": False, "error": f"No tab found for {domain}"}

        # Get screenshot
        screenshot_data = self.browser.screenshot_base64()

        # Get page content
        page_data = self.browser.read_page()

        # Analyze for login state
        page_text = page_data.get("content", "").lower()
        login_indicators = ["log in", "sign in", "sign up", "create account", "login", "signin"]
        logged_in_indicators = ["profile", "settings", "logout", "sign out", "account", "inbox", "messages"]

        is_logged_out = any(ind in page_text for ind in login_indicators)
        is_logged_in = any(ind in page_text for ind in logged_in_indicators)

        login_state = "unknown"
        if is_logged_in and not is_logged_out:
            login_state = "logged_in"
        elif is_logged_out and not is_logged_in:
            login_state = "logged_out"
        elif is_logged_in and is_logged_out:
            login_state = "mixed"  # Has both, probably logged in

        result = {
            "success": True,
            "domain": domain,
            "url": screenshot_data.get("url"),
            "title": screenshot_data.get("title"),
            "screenshot": screenshot_data.get("image"),
            "page_text": page_data.get("content", "")[:2000],
            "login_state": login_state,
            "observed_at": datetime.now().isoformat()
        }

        self.browser.disconnect()
        return result

    def detect_login_states(self, domains: List[str] = None) -> Dict[str, str]:
        """
        Detect login state for multiple domains.

        Returns: {"instagram.com": "logged_in", "twitter.com": "logged_out", ...}
        """
        if domains is None:
            # Use domains from open tabs
            tabs = self.get_all_tabs()
            domains = list(set(t["domain"] for t in tabs if t["domain"]))

        results = {}
        for domain in domains:
            observation = self.observe_site(domain)
            if observation.get("success"):
                results[domain] = observation.get("login_state", "unknown")
            else:
                results[domain] = "error"

        # Update state
        logged_in = [d for d, state in results.items() if state == "logged_in"]
        self.state["logged_in_sites"] = logged_in

        return results

    # =========================================================================
    # CONTACTS OBSERVATION
    # =========================================================================

    def get_imessage_contacts(self) -> List[Dict]:
        """
        Read iMessage database to get contacts.

        Returns list of:
        {
            "id": "+1234567890" or "email@example.com",
            "type": "phone" or "email",
            "display_name": "..." (if available)
        }
        """
        db_path = os.path.expanduser("~/Library/Messages/chat.db")

        if not os.path.exists(db_path):
            print("⚠ Messages database not found")
            return []

        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # Get all handles (contacts)
            cursor.execute("""
                SELECT DISTINCT id, service
                FROM handle
                ORDER BY id
            """)

            contacts = []
            for row in cursor.fetchall():
                contact_id = row[0]
                service = row[1]

                # Determine type
                if contact_id.startswith("+") or contact_id.replace("-", "").replace(" ", "").isdigit():
                    contact_type = "phone"
                elif "@" in contact_id:
                    contact_type = "email"
                else:
                    contact_type = "unknown"

                contacts.append({
                    "id": contact_id,
                    "type": contact_type,
                    "service": service
                })

            conn.close()

            # Update state
            self.state["contacts"] = contacts

            print(f"  Found {len(contacts)} iMessage contacts")
            return contacts

        except Exception as e:
            print(f"⚠ Error reading contacts: {e}")
            return []

    def find_contact(self, name: str) -> Optional[Dict]:
        """
        Find a contact by name (searches IDs for partial match).
        """
        contacts = self.state.get("contacts") or self.get_imessage_contacts()

        name_lower = name.lower()
        for contact in contacts:
            if name_lower in contact["id"].lower():
                return contact

        return None

    # =========================================================================
    # APPS OBSERVATION
    # =========================================================================

    def get_installed_apps(self) -> List[str]:
        """
        List installed applications from /Applications.
        """
        apps_dir = "/Applications"
        apps = []

        try:
            for item in os.listdir(apps_dir):
                if item.endswith(".app"):
                    apps.append(item.replace(".app", ""))

            # Update state
            self.state["apps"] = apps

            print(f"  Found {len(apps)} installed apps")
            return apps

        except Exception as e:
            print(f"⚠ Error listing apps: {e}")
            return []

    def is_app_installed(self, app_name: str) -> bool:
        """Check if an app is installed"""
        apps = self.state.get("apps") or self.get_installed_apps()
        return any(app_name.lower() in app.lower() for app in apps)

    # =========================================================================
    # FULL DISCOVERY
    # =========================================================================

    def discover_all(self, save: bool = True) -> Dict:
        """
        Full system discovery:
        - Browser tabs
        - Login states
        - iMessage contacts
        - Installed apps

        This is the "learn my system" command.
        """
        print("\n" + "=" * 60)
        print("🔍 SYSTEM DISCOVERY - Learning Your Setup")
        print("=" * 60)

        results = {
            "discovered_at": datetime.now().isoformat()
        }

        # Browser
        print("\n📱 Browser tabs...")
        browser_state = self.discover_browser_state()
        results["browser"] = {
            "total_tabs": browser_state["total_tabs"],
            "domains": browser_state["domains"]
        }

        # Login states (for top domains)
        print("\n🔐 Login states...")
        top_domains = browser_state["domains"][:10]  # Top 10
        login_states = {}
        for domain in top_domains:
            obs = self.observe_site(domain)
            if obs.get("success"):
                login_states[domain] = obs.get("login_state", "unknown")
                print(f"  {domain}: {obs.get('login_state', 'unknown')}")
        results["login_states"] = login_states
        self.state["logged_in_sites"] = [d for d, s in login_states.items() if s == "logged_in"]

        # Contacts
        print("\n📇 iMessage contacts...")
        contacts = self.get_imessage_contacts()
        results["contacts"] = {
            "total": len(contacts),
            "sample": [c["id"] for c in contacts[:5]]
        }

        # Apps
        print("\n📦 Installed apps...")
        apps = self.get_installed_apps()
        results["apps"] = {
            "total": len(apps),
            "sample": apps[:10]
        }

        if save:
            self.save_state()

        # Summary
        print("\n" + "=" * 60)
        print("✓ DISCOVERY COMPLETE")
        print("=" * 60)
        print(f"  Browser tabs: {browser_state['total_tabs']}")
        print(f"  Unique domains: {len(browser_state['domains'])}")
        print(f"  Logged in sites: {len(self.state.get('logged_in_sites', []))}")
        print(f"  iMessage contacts: {len(contacts)}")
        print(f"  Installed apps: {len(apps)}")
        print(f"\n  Saved to: {self.STATE_PATH}")

        return results

    # =========================================================================
    # QUERY METHODS
    # =========================================================================

    def is_logged_into(self, domain: str) -> bool:
        """Check if user is logged into a domain"""
        domain = domain.replace("www.", "")
        return domain in self.state.get("logged_in_sites", [])

    def get_open_domain_tab(self, domain: str) -> Optional[Dict]:
        """Get info about an open tab for a domain"""
        domain = domain.replace("www.", "")
        for tab in self.state.get("browser_tabs", []):
            if domain in tab.get("domain", ""):
                return tab
        return None

    def get_summary(self) -> str:
        """Get a human-readable summary of discovered state"""
        lines = []
        lines.append("System State Summary:")
        lines.append(f"  Discovered: {self.state.get('discovered_at', 'Never')}")
        lines.append(f"  Browser tabs: {len(self.state.get('browser_tabs', []))}")
        lines.append(f"  Logged in: {', '.join(self.state.get('logged_in_sites', []))}")
        lines.append(f"  Contacts: {len(self.state.get('contacts', []))}")
        lines.append(f"  Apps: {len(self.state.get('apps', []))}")
        return "\n".join(lines)


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import sys

    observer = SystemObserver()

    if len(sys.argv) > 1:
        cmd = sys.argv[1]

        if cmd == "discover":
            observer.discover_all()

        elif cmd == "tabs":
            tabs = observer.get_all_tabs()
            for tab in tabs:
                print(f"  {tab['domain']:30} {tab['title'][:40]}")

        elif cmd == "observe" and len(sys.argv) > 2:
            domain = sys.argv[2]
            result = observer.observe_site(domain)
            print(f"Domain: {result.get('domain')}")
            print(f"URL: {result.get('url')}")
            print(f"Title: {result.get('title')}")
            print(f"Login: {result.get('login_state')}")

        elif cmd == "contacts":
            contacts = observer.get_imessage_contacts()
            for c in contacts[:20]:
                print(f"  {c['type']:8} {c['id']}")

        elif cmd == "apps":
            apps = observer.get_installed_apps()
            for app in apps[:20]:
                print(f"  {app}")

        elif cmd == "summary":
            print(observer.get_summary())

        else:
            print("Usage: python system_observer.py [discover|tabs|observe <domain>|contacts|apps|summary]")

    else:
        print("Usage: python system_observer.py [discover|tabs|observe <domain>|contacts|apps|summary]")
