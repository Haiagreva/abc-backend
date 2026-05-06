print("GROQ VERSION DEPLOYED")
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
import os
import hashlib
import traceback
import json
import re
import base64
from algosdk.v2client import algod
from algosdk import transaction, mnemonic, account
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="ABC System Backend")

# Allow requests from React frontend (localhost dev + GitHub Pages)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Algorand setup ──────────────────────────────────────────────
algod_client = algod.AlgodClient(
    "",
    os.getenv("ALGOD_URL", "https://testnet-api.algonode.cloud"),
    headers={"X-Algo-API-Token": ""}
)

ALGO_MNEMONIC = os.getenv("ALGO_MNEMONIC")
ALGO_APP_ID   = int(os.getenv("APP_ID", "0"))
private_key   = mnemonic.to_private_key(ALGO_MNEMONIC)
sender_addr   = account.address_from_private_key(private_key)

# ── Groq setup (OpenAI-compatible) ─────────────────────────────
ai_client = OpenAI(
    api_key=os.getenv("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)

SYSTEM_PROMPT = """You are a fake news detection AI specialized in Indian political news.
Analyze the given post and return ONLY a JSON object with these exact fields:
{
  "score": <number 0-100, where 100 = definitely fake>,
  "verdict": <"LIKELY FAKE" | "SUSPICIOUS" | "LIKELY REAL">,
  "reason": <one sentence explanation, max 15 words>,
  "indicators": [<array of 2-3 short red/green flag strings>]
}
Return ONLY the JSON. No markdown, no explanation outside JSON."""


# ── Request/Response models ─────────────────────────────────────
class AnalyzeRequest(BaseModel):
    post_id: str
    content: str
    account_id: str


class AnalyzeResponse(BaseModel):
    post_id: str
    score: int
    verdict: str
    reason: str
    indicators: list[str]
    flagged: bool
    tx_id: str | None = None
    app_id: int | None = None


# ── Helper: write flag to Algorand ─────────────────────────────
def record_flag_on_chain(post_hash: str, account_id: str, score: int, verdict: str) -> str:
    """Submit a flag record transaction to the ABC smart contract."""
    try:
        sp = algod_client.suggested_params()

        txn = transaction.ApplicationCallTxn(
            sender=sender_addr,
            sp=sp,
            index=ALGO_APP_ID,
            on_complete=transaction.OnComplete.NoOpOC,
            app_args=[
                b"record_flag",
                post_hash.encode(),
                account_id.encode(),
                str(score).encode(),
                verdict.encode(),
            ],
            note=f"ABC|{post_hash[:16]}|{verdict}".encode(),
        )

        signed = txn.sign(private_key)
        tx_id = algod_client.send_transaction(signed)
        transaction.wait_for_confirmation(algod_client, tx_id, 4)
        return tx_id

    except Exception as e:
        print(f"⚠️  Chain write failed: {e}")
        return None


# ── Routes ──────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"status": "ABC System backend running", "app_id": ALGO_APP_ID}


@app.get("/health")
def health():
    try:
        status = algod_client.status()
        return {
            "status": "ok",
            "algorand": "connected",
            "last_round": status.get("last-round"),
            "app_id": ALGO_APP_ID,
            "signer": sender_addr,
        }
    except Exception as e:
        return {"status": "degraded", "error": str(e)}


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze_post(req: AnalyzeRequest):
    # 1. Run AI analysis
    try:
        response = ai_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT
                },
                {
                    "role": "user",
                    "content": f'Analyze this Indian political news post:\n\n"{req.content}"'
                }
            ],
            temperature=0.2
        )

        raw = response.choices[0].message.content

        print("RAW GROQ RESPONSE:")
        print(raw)

        raw = raw.strip()

        match = re.search(r'\{.*\}', raw, re.DOTALL)

        if not match:
            raise Exception(f"No JSON found: {raw}")

        json_text = match.group(0)

        result = json.loads(json_text)
    except Exception as e:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

    score   = int(result.get("score", 0))
    verdict = result.get("verdict", "UNKNOWN")
    reason  = result.get("reason", "")
    indicators = result.get("indicators", [])
    flagged = score >= 65

    # 2. If flagged, write to blockchain
    tx_id = None
    if flagged and ALGO_APP_ID > 0:
        post_hash = hashlib.sha256(req.content.encode()).hexdigest()
        tx_id = record_flag_on_chain(post_hash, req.account_id, score, verdict)
        if tx_id:
            print(f"⛓️  Flag recorded on-chain: {tx_id}")

    return AnalyzeResponse(
        post_id=req.post_id,
        score=score,
        verdict=verdict,
        reason=reason,
        indicators=indicators,
        flagged=flagged,
        tx_id=tx_id,
        app_id=ALGO_APP_ID if flagged else None,
    )


@app.get("/stats")
def get_stats():
    """Read global stats from the smart contract."""
    try:
        app_info = algod_client.application_info(ALGO_APP_ID)
        global_state = {}
        for kv in app_info["params"].get("global-state", []):
            key = base64.b64decode(kv["key"]).decode("utf-8", errors="ignore")
            val = kv["value"]
            if val["type"] == 2:
                global_state[key] = val["uint"]
            else:
                global_state[key] = base64.b64decode(val["bytes"]).decode("utf-8", errors="ignore")
        return {"app_id": ALGO_APP_ID, "global_state": global_state}
    except Exception as e:
        return {"error": str(e)}



print("GROQ VERSION DEPLOYED")