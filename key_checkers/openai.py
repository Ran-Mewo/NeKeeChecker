try:
    from .key_checker import KeyChecker
except ImportError:
    import os, sys
    sys.path.append(os.path.dirname(os.path.dirname(__file__)))
    from key_checkers.key_checker import KeyChecker
import urllib.request
import urllib.error
import json

class OpenAIKeyChecker(KeyChecker):
    TIER_BY_LIMITS = { # For gpt-5-nano
        (500, 200_000): "Tier_1",
        (5_000, 2_000_000): "Tier_2",
        (5_000, 4_000_000): "Tier_3",
        (10_000, 10_000_000): "Tier_4",
        (30_000, 180_000_000): "Tier_5",
    }
    def get_regex_pattern(self) -> str:
        return r"sk-[a-zA-Z0-9_-]+T3BlbkFJ[a-zA-Z0-9_-]+"

    def _tier_from_headers(self, headers) -> str:
        rpm = int((headers.get("x-ratelimit-limit-requests") or "0").replace(",", ""))
        tpm = int((headers.get("x-ratelimit-limit-tokens") or "0").replace(",", ""))
        return self.TIER_BY_LIMITS.get((rpm, tpm), "unknown")

    def verify_key(self, key: str):
        req = urllib.request.Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps({"model": "gpt-5-nano", "input": "Just say \"a\"", "max_output_tokens": 16}).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {key}",
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
                return
            if self.keys[key] == "dead":
                del self.keys[key]
                print("Deleted key", key, "because it is dead")
            else:
                self.keys[key] = "dead"
                print("Marked key", key, "as dead")
            self._save_keys()

