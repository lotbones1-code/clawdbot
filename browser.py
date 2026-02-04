"""
Browser Controller for ClawdBot v11.1
=====================================
Uses Playwright for reliable browser automation.
Can navigate, click, type, read pages, take screenshots, and verify actions.

NEW in v10: screenshot_base64() for Claude vision integration.
NEW in v11: scroll_find() to search scrolling lists for text.
NEW in v11.1: Connect to Comet browser first (has saved sessions!)
"""

import time
import json
import base64
import subprocess
from typing import Dict, List, Optional, Any

try:
    from playwright.sync_api import sync_playwright, Page, Browser, Playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


class BrowserController:
    """Controls a browser for web automation tasks"""

    def __init__(self):
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self._connected = False

    def connect(self) -> bool:
        """Connect to Comet browser first (has saved sessions!), then Chrome, then launch fresh"""
        if not PLAYWRIGHT_AVAILABLE:
            return False

        if self._connected and self.page:
            return True

        try:
            self.playwright = sync_playwright().start()

            # PRIORITY 1: Connect to Comet/Chrome on debug port (has saved logins!)
            for port in [9222, 9223]:
                try:
                    self.browser = self.playwright.chromium.connect_over_cdp(
                        f"http://localhost:{port}"
                    )
                    contexts = self.browser.contexts

                    print(f"✓ Connected to browser on port {port}")
                    print(f"  Found {len(contexts)} browser contexts")

                    # List ALL pages across ALL contexts with their URLs
                    all_pages = []
                    for i, ctx in enumerate(contexts):
                        ctx_pages = ctx.pages
                        print(f"  Context {i}: {len(ctx_pages)} pages")
                        for j, p in enumerate(ctx_pages):
                            try:
                                url = p.url
                                title = p.title()[:50] if p.title() else "No title"
                                print(f"    Page {j}: {url}")
                                all_pages.append(p)
                            except Exception as e:
                                print(f"    Page {j}: Error reading - {e}")

                    if all_pages:
                        # Find the BEST page - prefer one that's already on a useful site
                        best_page = None
                        priority_domains = ['instagram.com', 'twitter.com', 'x.com', 'facebook.com', 'youtube.com']

                        # First, look for a page on a priority domain
                        for p in all_pages:
                            try:
                                url = p.url.lower()
                                for domain in priority_domains:
                                    if domain in url:
                                        best_page = p
                                        print(f"  → Using existing {domain} tab!")
                                        break
                                if best_page:
                                    break
                            except:
                                pass

                        # If no priority domain, use first non-blank page
                        if not best_page:
                            for p in all_pages:
                                try:
                                    if p.url and 'about:blank' not in p.url and 'chrome://' not in p.url:
                                        best_page = p
                                        break
                                except:
                                    pass

                        # Last resort: first page
                        if not best_page:
                            best_page = all_pages[0]

                        self.page = best_page
                        print(f"  → Selected page: {self.page.url}")
                    else:
                        # No pages found, create one in existing context
                        print("  No existing pages, creating new tab...")
                        if contexts:
                            self.page = contexts[0].new_page()
                        else:
                            context = self.browser.new_context()
                            self.page = context.new_page()

                    self._connected = True
                    return True
                except Exception as e:
                    print(f"  Failed to connect on port {port}: {e}")
                    pass

            # PRIORITY 2: Try to START Comet with debug port
            try:
                print("Starting Comet browser with debug port...")
                subprocess.Popen([
                    '/Applications/Comet.app/Contents/MacOS/Comet',
                    '--remote-debugging-port=9222',
                    '--remote-allow-origins=*'
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(3)

                self.browser = self.playwright.chromium.connect_over_cdp("http://localhost:9222")
                contexts = self.browser.contexts
                if contexts:
                    self.page = contexts[0].pages[0] if contexts[0].pages else contexts[0].new_page()
                else:
                    context = self.browser.new_context()
                    self.page = context.new_page()
                self._connected = True
                print("✓ Started Comet with debug port (saved sessions available)")
                return True
            except:
                pass

            # PRIORITY 3: Launch fresh Playwright browser (NO saved sessions!)
            print("⚠ Warning: Launching fresh browser - NO saved logins!")
            print("  To use saved sessions, start Comet first:")
            print("  /Applications/Comet.app/Contents/MacOS/Comet --remote-debugging-port=9222 &")
            self.browser = self.playwright.chromium.launch(
                headless=False,
                args=['--start-maximized']
            )
            self.page = self.browser.new_page()
            self._connected = True
            return True

        except Exception as e:
            print(f"Browser connect error: {e}")
            return False

    def disconnect(self):
        """Close browser connection"""
        try:
            if self.browser:
                self.browser.close()
            if self.playwright:
                self.playwright.stop()
        except:
            pass
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected and self.page is not None

    def _get_all_pages(self) -> List[Page]:
        """Get all open pages/tabs across all contexts"""
        pages = []
        if self.browser:
            for context in self.browser.contexts:
                pages.extend(context.pages)
        return pages

    def _find_page_with_domain(self, domain: str) -> Optional[Page]:
        """Find an existing page/tab that has the given domain"""
        domain = domain.lower().replace("www.", "")
        for page in self._get_all_pages():
            try:
                page_url = page.url.lower()
                if domain in page_url:
                    return page
            except:
                pass
        return None

    # =========================================================================
    # NAVIGATION
    # =========================================================================

    def navigate(self, url: str) -> Dict:
        """Navigate to a URL - FIRST checks for existing tabs with that domain"""
        if not self.connect():
            return {"success": False, "error": "Could not connect to browser"}

        try:
            if not url.startswith("http"):
                url = "https://" + url

            # Extract domain from URL
            from urllib.parse import urlparse
            domain = urlparse(url).netloc.replace("www.", "")

            print(f"[NAV] Want to go to: {domain}")
            print(f"[NAV] Current page: {self.page.url}")

            # List all available pages
            all_pages = self._get_all_pages()
            print(f"[NAV] Scanning {len(all_pages)} tabs for {domain}...")

            # FIRST: Check if we already have a tab with this domain (logged in!)
            existing_page = self._find_page_with_domain(domain)
            if existing_page:
                print(f"[NAV] ✓ Found existing {domain} tab!")
                print(f"[NAV]   URL: {existing_page.url}")
                self.page = existing_page
                try:
                    self.page.bring_to_front()
                except:
                    pass  # bring_to_front may not work with CDP
                time.sleep(0.5)
                return {
                    "success": True,
                    "url": self.page.url,
                    "title": self.page.title(),
                    "reused_tab": True
                }

            print(f"[NAV] No existing {domain} tab found, navigating...")

            # No existing tab - navigate current page
            self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(1)  # Let page settle

            return {
                "success": True,
                "url": self.page.url,
                "title": self.page.title()
            }
        except Exception as e:
            print(f"[NAV] Error: {e}")
            return {"success": False, "error": str(e)}

    def get_current_url(self) -> str:
        """Get current page URL"""
        if self.page:
            return self.page.url
        return ""

    # =========================================================================
    # READING PAGE CONTENT
    # =========================================================================

    def read_page(self) -> Dict:
        """Read the visible text content of the page"""
        if not self.is_connected():
            return {"success": False, "error": "Not connected"}

        try:
            # Get visible text
            text = self.page.inner_text("body")

            # Truncate if too long
            if len(text) > 5000:
                text = text[:5000] + "\n... [truncated]"

            return {
                "success": True,
                "url": self.page.url,
                "title": self.page.title(),
                "content": text
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def find_elements(self, description: str) -> Dict:
        """Find elements matching a description"""
        if not self.is_connected():
            return {"success": False, "error": "Not connected"}

        try:
            elements = []

            # Common element patterns based on description
            description_lower = description.lower()

            if "button" in description_lower:
                # Find all buttons
                buttons = self.page.query_selector_all("button, [role='button'], input[type='submit']")
                for btn in buttons[:20]:
                    text = btn.inner_text() or btn.get_attribute("aria-label") or ""
                    elements.append({
                        "type": "button",
                        "text": text.strip()[:50],
                        "visible": btn.is_visible()
                    })

            elif "link" in description_lower:
                links = self.page.query_selector_all("a[href]")
                for link in links[:20]:
                    text = link.inner_text() or link.get_attribute("aria-label") or ""
                    href = link.get_attribute("href") or ""
                    elements.append({
                        "type": "link",
                        "text": text.strip()[:50],
                        "href": href[:100]
                    })

            elif "input" in description_lower or "field" in description_lower:
                inputs = self.page.query_selector_all("input, textarea")
                for inp in inputs[:20]:
                    placeholder = inp.get_attribute("placeholder") or ""
                    name = inp.get_attribute("name") or ""
                    elements.append({
                        "type": "input",
                        "placeholder": placeholder,
                        "name": name
                    })

            else:
                # Generic search - find elements containing the text
                all_elements = self.page.query_selector_all(f"text={description}")
                for el in all_elements[:10]:
                    elements.append({
                        "type": "element",
                        "text": el.inner_text()[:50] if el.inner_text() else ""
                    })

            return {
                "success": True,
                "count": len(elements),
                "elements": elements
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # =========================================================================
    # INTERACTIONS
    # =========================================================================

    def click(self, target: str) -> Dict:
        """Click on an element by text or selector"""
        if not self.is_connected():
            return {"success": False, "error": "Not connected"}

        try:
            # Try different strategies

            # 1. Try as text content
            try:
                self.page.click(f"text={target}", timeout=5000)
                return {"success": True, "clicked": target, "method": "text"}
            except:
                pass

            # 2. Try as button with text
            try:
                self.page.click(f"button:has-text('{target}')", timeout=3000)
                return {"success": True, "clicked": target, "method": "button_text"}
            except:
                pass

            # 3. Try as link with text
            try:
                self.page.click(f"a:has-text('{target}')", timeout=3000)
                return {"success": True, "clicked": target, "method": "link_text"}
            except:
                pass

            # 4. Try as role button with name
            try:
                self.page.click(f"[role='button']:has-text('{target}')", timeout=3000)
                return {"success": True, "clicked": target, "method": "role_button"}
            except:
                pass

            # 5. Try as CSS selector directly
            try:
                self.page.click(target, timeout=3000)
                return {"success": True, "clicked": target, "method": "selector"}
            except:
                pass

            return {"success": False, "error": f"Could not find clickable element: {target}"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def click_nth(self, target: str, index: int = 0) -> Dict:
        """Click the nth element matching the target"""
        if not self.is_connected():
            return {"success": False, "error": "Not connected"}

        try:
            elements = self.page.query_selector_all(f"text={target}")
            if not elements:
                elements = self.page.query_selector_all(f"button:has-text('{target}')")
            if not elements:
                elements = self.page.query_selector_all(f"[role='button']:has-text('{target}')")

            if elements and len(elements) > index:
                elements[index].click()
                return {"success": True, "clicked": f"{target} #{index}"}

            return {"success": False, "error": f"Element #{index} not found for: {target}"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def type_text(self, text: str, field: str = None) -> Dict:
        """Type text into focused element or specified field"""
        if not self.is_connected():
            return {"success": False, "error": "Not connected"}

        try:
            if field:
                # Find and focus the field first
                try:
                    self.page.click(f"[placeholder*='{field}']", timeout=3000)
                except:
                    try:
                        self.page.click(f"input[name*='{field}']", timeout=3000)
                    except:
                        self.page.click(f"text={field}", timeout=3000)

            # Type the text
            self.page.keyboard.type(text, delay=50)

            return {"success": True, "typed": text[:50]}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def press_key(self, key: str) -> Dict:
        """Press a keyboard key (Enter, Tab, Escape, etc)"""
        if not self.is_connected():
            return {"success": False, "error": "Not connected"}

        try:
            self.page.keyboard.press(key)
            return {"success": True, "pressed": key}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def scroll(self, direction: str = "down", amount: int = 500) -> Dict:
        """Scroll the page"""
        if not self.is_connected():
            return {"success": False, "error": "Not connected"}

        try:
            if direction == "down":
                self.page.mouse.wheel(0, amount)
            elif direction == "up":
                self.page.mouse.wheel(0, -amount)

            time.sleep(0.5)
            return {"success": True, "scrolled": direction}

        except Exception as e:
            return {"success": False, "error": str(e)}

    # =========================================================================
    # VERIFICATION
    # =========================================================================

    def wait_for_text(self, text: str, timeout: int = 10000) -> Dict:
        """Wait for text to appear on page"""
        if not self.is_connected():
            return {"success": False, "error": "Not connected"}

        try:
            self.page.wait_for_selector(f"text={text}", timeout=timeout)
            return {"success": True, "found": text}
        except:
            return {"success": False, "error": f"Text not found: {text}"}

    def has_text(self, text: str) -> bool:
        """Check if page contains text"""
        if not self.is_connected():
            return False

        try:
            content = self.page.inner_text("body")
            return text.lower() in content.lower()
        except:
            return False

    def scroll_find(self, text: str, max_scrolls: int = 15) -> Dict:
        """Scroll down looking for text, return when found (for infinite scroll lists)"""
        if not self.is_connected():
            return {"success": False, "error": "Not connected"}

        try:
            for i in range(max_scrolls):
                # Check if text is visible
                if self.has_text(text):
                    return {
                        "success": True,
                        "found": text,
                        "scrolls": i,
                        "message": f"Found '{text}' after {i} scrolls"
                    }

                # Scroll down
                self.page.mouse.wheel(0, 400)
                time.sleep(0.8)  # Wait for content to load

            return {
                "success": False,
                "error": f"'{text}' not found after {max_scrolls} scrolls"
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def screenshot(self, path: str = None) -> Dict:
        """Take a screenshot and save to file"""
        if not self.is_connected():
            return {"success": False, "error": "Not connected"}

        try:
            if not path:
                path = "/tmp/clawdbot_screenshot.png"

            self.page.screenshot(path=path)
            return {"success": True, "path": path}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def screenshot_base64(self) -> Dict:
        """Take a screenshot and return as base64 for Claude vision"""
        if not self.is_connected():
            return {"success": False, "error": "Not connected"}

        try:
            # Get screenshot as bytes
            png_bytes = self.page.screenshot(type="png")
            # Convert to base64
            b64_string = base64.b64encode(png_bytes).decode("utf-8")

            return {
                "success": True,
                "image": b64_string,
                "url": self.page.url,
                "title": self.page.title()
            }

        except Exception as e:
            return {"success": False, "error": str(e)}


# Singleton instance
_browser = None

def get_browser() -> BrowserController:
    """Get or create the browser controller singleton"""
    global _browser
    if _browser is None:
        _browser = BrowserController()
    return _browser
