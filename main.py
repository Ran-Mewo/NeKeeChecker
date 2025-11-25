import json
import os
import secrets
from typing import Any

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi_utils.tasks import repeat_every

from key_checkers.openai import OpenAIKeyChecker
from key_checkers.anthropic import AnthropicKeyChecker
from key_checkers.google import GoogleKeyChecker
from key_checkers.elevenlabs import ElevenLabsKeyChecker
from key_checkers.openrouter import OpenRouterKeyChecker
from key_checkers.aws import AWSKeyChecker

load_dotenv()

PASSWORD = os.getenv("NEKEE_PASSWORD")
USERNAME = os.getenv("NEKEE_USERNAME", "admin")

if not PASSWORD:
    raise RuntimeError("NEKEE_PASSWORD must be set in the environment")


class PrettyJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:  # type: ignore[override]
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            separators=(", ", ": "),
        ).encode("utf-8")


app = FastAPI(default_response_class=PrettyJSONResponse)
security = HTTPBasic()

key_checkers = [
    OpenAIKeyChecker(),
    AnthropicKeyChecker(),
    GoogleKeyChecker(),
    ElevenLabsKeyChecker(),
    OpenRouterKeyChecker(),
    AWSKeyChecker(),
]


async def _require_password(credentials: HTTPBasicCredentials = Depends(security)) -> None:
    username_matches = secrets.compare_digest(credentials.username or "", USERNAME)
    password_matches = secrets.compare_digest(credentials.password or "", PASSWORD)
    if not username_matches or not password_matches:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
            headers={"WWW-Authenticate": 'Basic realm="NeKee"'},
        )


@app.get("/", dependencies=[Depends(_require_password)])
async def root():
    summary = {}
    for checker in key_checkers:
        active_keys = checker.list_keys_by_tiers()
        summary[checker.get_name()] = {
            "count": sum(len(keys) for keys in active_keys.values()),
            "keys": active_keys,
            "keys_with_special_features": list(checker.keys_with_special_features),
            "usage_reached_keys": list(checker.monthly_usage_reached_keys),
        }
    return summary


@app.post("/data", status_code=status.HTTP_204_NO_CONTENT)
async def receive_text(request: Request, background_tasks: BackgroundTasks):
    text = (await request.body()).decode('utf-8')
    for checker in key_checkers:
        background_tasks.add_task(checker.check_text, text)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _get_checker_or_404(name: str):
    for c in key_checkers:
        if c.get_name() == name:
            return c
    raise HTTPException(status_code=404, detail="checker not found")


@app.get("/list/{checker_name}", dependencies=[Depends(_require_password)])
async def list_checker_tiers(checker_name: str):
    return  _get_checker_or_404(checker_name).list_keys_by_tiers()


@app.get("/list/{checker_name}/{tier}", dependencies=[Depends(_require_password)])
async def list_checker_by_tier(checker_name: str, tier: str):
    return _get_checker_or_404(checker_name).list_keys(tier)


@app.get("/{checker_name}", dependencies=[Depends(_require_password)])
async def get_random_key(checker_name: str):
    return _get_checker_or_404(checker_name).get_key()


@app.get("/{checker_name}/{tier}", dependencies=[Depends(_require_password)])
async def get_random_key_by_tier(checker_name: str, tier: str):
    return _get_checker_or_404(checker_name).get_key(tier)

@app.on_event("startup")
@repeat_every(seconds=60 * 60 * 24 * 2, wait_first=False)
def verify_all_keys_monthly():
    for checker in key_checkers:
        for key in list(checker.monthly_usage_reached_keys):
            checker.verify_key(key)

@app.on_event("startup")
@repeat_every(seconds=60 * 60 * 24 * 0.5, wait_first=True)
def verify_all_keys_daily():
    for checker in key_checkers:
        for key in list(checker.keys.keys()):
            checker.verify_key(key)