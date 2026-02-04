"""
Browser Controller using Direct CDP (Chrome DevTools Protocol)
==============================================================
Uses websockets to connect directly to Comet browser.
Much faster and more reliable than Playwright for browsers with many tabs.

This replaces the Playwright-based browser.py for ClawdBot.
"""

import time
import json
import base64
import urllib.request
from typing import Dict, List, Optional, Any

try:
    import websocket
    WEBSOCKET_AVAILABLE = True
except ImportError:
    WEBSOCKET_AVAILABLE = False


class BrowserCDP:
    """Direct CDP browser controller - connects to YOUR Comet browser"""

    def __init__(self):
        self.ws: Optional[websocket.WebSocket] = None
        self.page_id: Optional[str] = None
        self.page_url: str = ""
        self.page_title: str = ""
        self._msg_id = 0
        self._connected = False

    def _get_targets(self) -> List[Dict]:
        """Get all browser targets from CDP"""
        try:
            data = urllib.request.urlopen("http://localhost:9222/json/list", timeout=5).read()
            return json.loads(data)
        except:
            return []

    def _find_page(self, domain: str = None) -> Optional[Dict]:
        """Find a page target, optionally matching a domain"""
        targets = self._get_targets()
        pages = [t for t in targets if t.get('type') == 'page']

        if domain:
            domain = domain.lower().replace('www.', '')
            for page in pages:
                if domain in page.get('url', '').lower():
                    return page

        # Return first non-chrome page
        for page in pages:
            url = page.get('url', '')
            if not url.startswith('chrome://') and 'about:blank' not in url:
                return page

        return pages[0] if pages else None

    def connect(self, domain: str = None) -> bool:
        """Connect to browser, optionally to a specific domain's page"""
        if not WEBSOCKET_AVAILABLE:
            print("Error: websocket-client not installed. Run: pip install websocket-client")
            return False

        try:
            # Find page to connect to
            page_info = self._find_page(domain)
            if not page_info:
                print("No browser pages found. Is Comet running with --remote-debugging-port=9222?")
                return False

            ws_url = page_info.get('webSocketDebuggerUrl')
            if not ws_url:
                print("No WebSocket URL for page")
                return False

            # Connect
            self.ws = websocket.create_connection(ws_url, timeout=10)
            self.page_id = page_info.get('id')
            self.page_url = page_info.get('url', '')
            self.page_title = page_info.get('title', '')
            self._connected = True

            print(f"✓ Connected to: {self.page_title[:50]}")
            print(f"  URL: {self.page_url[:70]}")
            return True

        except Exception as e:
            print(f"Connection error: {e}")
            return False

    def disconnect(self):
        """Close websocket connection"""
        if self.ws:
            try:
                self.ws.close()
            except:
                pass
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected and self.ws is not None

    def _send_cdp(self, method: str, params: Dict = None) -> Dict:
        """Send a CDP command and get response"""
        if not self.ws:
            return {"error": "Not connected"}

        self._msg_id += 1
        msg = {"id": self._msg_id, "method": method}
        if params:
            msg["params"] = params

        try:
            self.ws.send(json.dumps(msg))
            # Read until we get our response
            while True:
                result = json.loads(self.ws.recv())
                if result.get('id') == self._msg_id:
                    return result
        except Exception as e:
            return {"error": str(e)}

    # =========================================================================
    # NAVIGATION
    # =========================================================================

    def navigate(self, url: str) -> Dict:
        """Navigate to a URL - checks for existing tabs first"""
        if not url.startswith("http"):
            url = "https://" + url

        # Extract domain
        from urllib.parse import urlparse
        domain = urlparse(url).netloc.replace("www.", "")

        # Check if there's already a tab with this domain
        existing = self._find_page(domain)
        if existing and domain in existing.get('url', '').lower():
            # Switch to that tab
            print(f"✓ Found existing {domain} tab - switching to it!")
            self.disconnect()
            self.ws = websocket.create_connection(existing['webSocketDebuggerUrl'], timeout=10)
            self.page_id = existing['id']
            self.page_url = existing['url']
            self.page_title = existing['title']
            self._connected = True
            return {
                "success": True,
                "url": self.page_url,
                "title": self.page_title,
                "reused_tab": True
            }

        # Navigate current page
        if not self.is_connected():
            if not self.connect():
                return {"success": False, "error": "Could not connect"}

        result = self._send_cdp("Page.navigate", {"url": url})
        if "error" in result:
            return {"success": False, "error": result.get("error")}

        time.sleep(1.5)  # Wait for page load
        self.page_url = url
        return {"success": True, "url": url}

    def get_current_url(self) -> str:
        return self.page_url

    # =========================================================================
    # READING PAGE CONTENT
    # =========================================================================

    def read_page(self) -> Dict:
        """Read page content"""
        if not self.is_connected():
            return {"success": False, "error": "Not connected"}

        # Get document
        result = self._send_cdp("Runtime.evaluate", {
            "expression": "document.body.innerText",
            "returnByValue": True
        })

        if "error" in result:
            return {"success": False, "error": result.get("error")}

        text = result.get('result', {}).get('result', {}).get('value', '')
        if len(text) > 5000:
            text = text[:5000] + "\n... [truncated]"

        return {
            "success": True,
            "url": self.page_url,
            "title": self.page_title,
            "content": text
        }

    # =========================================================================
    # SCREENSHOTS
    # =========================================================================

    def screenshot(self, path: str = None) -> Dict:
        """Take screenshot and save to file"""
        if not self.is_connected():
            return {"success": False, "error": "Not connected"}

        result = self._send_cdp("Page.captureScreenshot", {"format": "png"})
        if "error" in result:
            return {"success": False, "error": result.get("error")}

        data = result.get('result', {}).get('data')
        if not data:
            return {"success": False, "error": "No screenshot data"}

        if not path:
            path = "/tmp/clawdbot_screenshot.png"

        img_bytes = base64.b64decode(data)
        with open(path, 'wb') as f:
            f.write(img_bytes)

        return {"success": True, "path": path}

    def screenshot_base64(self) -> Dict:
        """Take screenshot and return as base64 for Claude vision"""
        if not self.is_connected():
            return {"success": False, "error": "Not connected"}

        result = self._send_cdp("Page.captureScreenshot", {"format": "png"})
        if "error" in result:
            return {"success": False, "error": result.get("error")}

        data = result.get('result', {}).get('data')
        if not data:
            return {"success": False, "error": "No screenshot data"}

        return {
            "success": True,
            "image": data,
            "url": self.page_url,
            "title": self.page_title
        }

    # =========================================================================
    # INTERACTIONS
    # =========================================================================

    def click(self, target: str) -> Dict:
        """Click on an element by text"""
        if not self.is_connected():
            return {"success": False, "error": "Not connected"}

        # Find element by text and click it
        js = f'''
        (function() {{
            // Try to find element with matching text
            const xpath = "//*[contains(text(), '{target}')]";
            const result = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
            const elem = result.singleNodeValue;
            if (elem) {{
                elem.click();
                return "clicked: " + elem.tagName;
            }}

            // Try buttons/links with aria-label
            const ariaElem = document.querySelector(`[aria-label*="${target}" i]`);
            if (ariaElem) {{
                ariaElem.click();
                return "clicked aria: " + ariaElem.tagName;
            }}

            // Try buttons with text
            const buttons = Array.from(document.querySelectorAll('button, a, [role="button"]'));
            for (const btn of buttons) {{
                if (btn.textContent.toLowerCase().includes("{target.lower()}")) {{
                    btn.click();
                    return "clicked button: " + btn.textContent.slice(0, 30);
                }}
            }}

            return "not found";
        }})()
        '''

        result = self._send_cdp("Runtime.evaluate", {"expression": js, "returnByValue": True})
        value = result.get('result', {}).get('result', {}).get('value', 'error')

        if "clicked" in str(value):
            return {"success": True, "clicked": target, "details": value}
        return {"success": False, "error": f"Could not find: {target}"}

    def click_nth(self, target: str, index: int = 0) -> Dict:
        """Click the nth element matching target"""
        if not self.is_connected():
            return {"success": False, "error": "Not connected"}

        js = f'''
        (function() {{
            const elements = Array.from(document.querySelectorAll('button, a, [role="button"], span, div'))
                .filter(el => el.textContent.toLowerCase().includes("{target.lower()}"));
            if (elements.length > {index}) {{
                elements[{index}].click();
                return "clicked #" + {index};
            }}
            return "not found at index {index}";
        }})()
        '''

        result = self._send_cdp("Runtime.evaluate", {"expression": js, "returnByValue": True})
        value = result.get('result', {}).get('result', {}).get('value', 'error')

        if "clicked" in str(value):
            return {"success": True, "clicked": f"{target} #{index}"}
        return {"success": False, "error": value}

    def type_text(self, text: str, field: str = None) -> Dict:
        """Type text into focused element or specified field"""
        if not self.is_connected():
            return {"success": False, "error": "Not connected"}

        # If field specified, focus it first
        if field:
            focus_js = f'''
            (function() {{
                const input = document.querySelector(`[placeholder*="{field}" i], [aria-label*="{field}" i], input[name*="{field}" i]`);
                if (input) {{
                    input.focus();
                    return "focused";
                }}
                return "not found";
            }})()
            '''
            self._send_cdp("Runtime.evaluate", {"expression": focus_js})

        # Type the text
        for char in text:
            self._send_cdp("Input.dispatchKeyEvent", {
                "type": "keyDown",
                "text": char
            })
            self._send_cdp("Input.dispatchKeyEvent", {
                "type": "keyUp",
                "text": char
            })
            time.sleep(0.03)

        return {"success": True, "typed": text[:50]}

    def press_key(self, key: str) -> Dict:
        """Press a keyboard key"""
        if not self.is_connected():
            return {"success": False, "error": "Not connected"}

        key_codes = {
            "Enter": {"keyCode": 13, "code": "Enter", "key": "Enter"},
            "Tab": {"keyCode": 9, "code": "Tab", "key": "Tab"},
            "Escape": {"keyCode": 27, "code": "Escape", "key": "Escape"},
            "Backspace": {"keyCode": 8, "code": "Backspace", "key": "Backspace"},
        }

        key_info = key_codes.get(key, {"key": key})

        self._send_cdp("Input.dispatchKeyEvent", {"type": "keyDown", **key_info})
        self._send_cdp("Input.dispatchKeyEvent", {"type": "keyUp", **key_info})

        return {"success": True, "pressed": key}

    def scroll(self, direction: str = "down", amount: int = 500) -> Dict:
        """Scroll the page"""
        if not self.is_connected():
            return {"success": False, "error": "Not connected"}

        delta_y = amount if direction == "down" else -amount

        self._send_cdp("Input.dispatchMouseEvent", {
            "type": "mouseWheel",
            "x": 400,
            "y": 300,
            "deltaX": 0,
            "deltaY": delta_y
        })

        time.sleep(0.5)
        return {"success": True, "scrolled": direction}

    def scroll_find(self, text: str, max_scrolls: int = 15) -> Dict:
        """Scroll down looking for text"""
        if not self.is_connected():
            return {"success": False, "error": "Not connected"}

        for i in range(max_scrolls):
            # Check if text is on page
            result = self._send_cdp("Runtime.evaluate", {
                "expression": f"document.body.innerText.toLowerCase().includes('{text.lower()}')",
                "returnByValue": True
            })
            found = result.get('result', {}).get('result', {}).get('value', False)

            if found:
                return {"success": True, "found": text, "scrolls": i}

            # Scroll down
            self.scroll("down", 400)
            time.sleep(0.8)

        return {"success": False, "error": f"'{text}' not found after {max_scrolls} scrolls"}

    def has_text(self, text: str) -> bool:
        """Check if page contains text"""
        if not self.is_connected():
            return False

        result = self._send_cdp("Runtime.evaluate", {
            "expression": f"document.body.innerText.toLowerCase().includes('{text.lower()}')",
            "returnByValue": True
        })
        return result.get('result', {}).get('result', {}).get('value', False)

    def wait_for_text(self, text: str, timeout: int = 10000) -> Dict:
        """Wait for text to appear"""
        if not self.is_connected():
            return {"success": False, "error": "Not connected"}

        start = time.time()
        while (time.time() - start) * 1000 < timeout:
            if self.has_text(text):
                return {"success": True, "found": text}
            time.sleep(0.5)

        return {"success": False, "error": f"Text not found: {text}"}


# Singleton
_browser_cdp = None

def get_browser_cdp() -> BrowserCDP:
    """Get or create the CDP browser controller singleton"""
    global _browser_cdp
    if _browser_cdp is None:
        _browser_cdp = BrowserCDP()
    return _browser_cdp
