"""Direct HITL action endpoints (Phase-4).

Exposes POST /api/v1/actions/pause advertised in README and simulate_live_store.py.
Reuses shared execute_hitl_token_action() helper — zero duplication with WhatsApp path.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from loguru import logger
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import verify_api_key_dependency
from app.skills.hitl_action_tokens import (
    ExpiredTokenError,
    InvalidTokenError,
    execute_hitl_token_action,
)
from app.utils.meta_client import MetaAPIError

router = APIRouter()


class PauseRequest(BaseModel):
    token: str | None = None


@router.post("/pause")
async def pause_campaign(
    request: Request,
    body: PauseRequest | None = None,
    token: str | None = Query(default=None, description="HITL action token (?token=...)"),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_api_key_dependency),
) -> dict:
    """Direct action endpoint: pause a campaign via signed HITL token.

    Accepts {"token": "v1.PAUSE..."} JSON body or ?token= query param.
    """
    raw_token = (body.token if body and body.token else None) or token
    if not raw_token:
        # Also support raw JSON {"token": ...} parsed manually for robustness
        try:
            payload = await request.json()
            if isinstance(payload, dict) and payload.get("token"):
                raw_token = payload["token"]
        except Exception:
            pass
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Missing HITL action token. Provide JSON {\"token\": ...} or ?token=...",
        )
    try:
        result = await execute_hitl_token_action(raw_token)
    except ExpiredTokenError as exc:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=f"Action token expired: {exc}")
    except InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid action token: {exc}")
    except MetaAPIError as exc:
        logger.error(f"Meta pause failed via direct endpoint: {exc}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Meta API error: {exc}")
    if result.get("status") == "duplicate":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Action token already processed.")
    if result.get("status") not in ("paused", "dismissed"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported action result: {result}")
    return result
