from fastapi import APIRouter, HTTPException

from app.services.nuvio_simkl_sync import (
    is_enabled,
    last_result,
    set_enabled,
    sync_nuvio_library_to_simkl,
)
from app.services.token_store import token_store

router = APIRouter(tags=["Nuvio Simkl Sync"])


async def _require_token(token: str) -> None:
    resolved = await token_store.resolve_alias(token)
    if not await token_store.get_user_data(resolved):
        raise HTTPException(status_code=404, detail="Watchly token not found")


@router.get("/{token}/sync/nuvio-simkl")
async def nuvio_simkl_status(token: str):
    await _require_token(token)
    return {"enabled": await is_enabled(token), "last_sync": await last_result(token)}


@router.post("/{token}/sync/nuvio-simkl")
async def nuvio_simkl_sync_now(token: str):
    await _require_token(token)
    try:
        result = await sync_nuvio_library_to_simkl(token)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result.to_dict()


@router.post("/{token}/sync/nuvio-simkl/enable")
async def enable_nuvio_simkl_sync(token: str):
    await _require_token(token)
    # Run before enabling so bad/missing provider credentials cannot leave a
    # permanently failing background job behind.
    try:
        result = await sync_nuvio_library_to_simkl(token)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await set_enabled(token, True)
    return {"enabled": True, "last_sync": result.to_dict()}


@router.post("/{token}/sync/nuvio-simkl/disable")
async def disable_nuvio_simkl_sync(token: str):
    await _require_token(token)
    await set_enabled(token, False)
    return {"enabled": False, "last_sync": await last_result(token)}
