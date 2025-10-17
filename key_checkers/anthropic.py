try:
    from .key_checker import KeyChecker
except ImportError:
    import os, sys
    sys.path.append(os.path.dirname(os.path.dirname(__file__)))
    from key_checkers.key_checker import KeyChecker
import urllib.request
import urllib.error
import json

class AnthropicKeyChecker(KeyChecker):
    TIER_BY_LIMITS = {
        50: "Tier_1",
        1_000: "Tier_2",
        2_000: "Tier_3",
        4_000: "Tier_4",
    }
    def get_regex_pattern(self) -> str:
        return r"sk-ant-(?:admin01|api03)-[A-Za-z0-9_-]{93}AA"

    def _tier_from_headers(self, headers) -> str:
        rpm = int((headers.get("anthropic-ratelimit-requests-limit") or "0").replace(",", ""))
        return self.TIER_BY_LIMITS.get(rpm, "Tier_5")

    def verify_key(self, key: str):
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps({"model": "claude-3-haiku-20240307", "max_tokens": 16, "messages": [{"role": "user", "content": "Just say \"a\""}]}).encode("utf-8"),
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
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
                return
            if self.keys[key] == "dead":
                del self.keys[key]
                print("Deleted key", key, "because it is dead")
            else:
                self.keys[key] = "dead"
                print("Marked key", key, "as dead")
            self._save_keys()
