try:
    from .key_checker import KeyChecker
except ImportError:
    import os
    import sys

    sys.path.append(os.path.dirname(os.path.dirname(__file__)))
    from key_checkers.key_checker import KeyChecker

import json
import urllib.error
import urllib.request


class GoogleKeyChecker(KeyChecker):
    TIER_BY_LIMITS = { # For gemini-2.5-flash-lite
        (15, 250_000): "Free",
        (4_000, 4_000_000): "Tier_1",
        (10_000, 10_000_000): "Tier_2",
        (30_000, 30_000_000): "Tier_3",
    }

    def get_regex_pattern(self) -> str:
        return r"AIza[0-9A-Za-z\-_]{35}"

    def _tier_from_headers(self, headers) -> str:
        # Gemini API doesn't return any headers for rate limiting yet.
        return "unknown"

    def verify_key(self, key: str):
        if key in self.invalid_keys:
            return

        req = urllib.request.Request(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent",
            data=json.dumps({"contents": [{"parts": [{"text": "Just say \"a\""}]}]}).encode("utf-8"),
            headers={
                "x-goog-api-key": key,
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                self.keys[key] = self._tier_from_headers(resp.headers)
                print("Verified key", key, "with tier", self.keys[key])
                self._save_keys()
                return True
        except urllib.error.HTTPError:
            if key not in self.keys:
                print("Not a valid key", key)
                self.invalid_keys.append(key)
                return
            if self.keys[key] == "dead":
                del self.keys[key]
                print("Deleted key", key, "because it is dead")
            else:
                self.keys[key] = "dead"
                print("Marked key", key, "as dead")
            self._save_keys()


