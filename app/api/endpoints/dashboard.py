from fastapi import APIRouter, HTTPException

from app.services.dashboard import dashboard_service
from app.services.reroll import reroll_service

router = APIRouter(tags=["Dashboard"])


@router.get("/{token}/dashboard/data")
async def dashboard_data(token: str):
    data = await dashboard_service.get_data(token)
    if data is None:
        raise HTTPException(status_code=404, detail="Token not found. Please reconfigure the addon.")
    return data


@router.post("/{token}/dashboard/refresh")
async def dashboard_refresh(token: str):
    if not await dashboard_service.refresh(token):
        raise HTTPException(status_code=404, detail="Token not found. Please reconfigure the addon.")
    return {"status": "started"}


@router.post("/{token}/refresh-recommendations")
async def refresh_recommendations(token: str):
    """Force a fresh history/profile/catalog rebuild regardless of cache age."""
    if not await dashboard_service.refresh(token):
        raise HTTPException(status_code=404, detail="Token not found. Please reconfigure the addon.")
    return {
        "status": "started",
        "detail": (
            "Fresh history and recommendations are rebuilding in the background. "
            "An existing Watchly Nuvio collection will be reconciled when the rebuild finishes."
        ),
    }


@router.post("/{token}/reroll-recommendations")
async def reroll_recommendations(token: str):
    """Replace the currently served recommendation batches without changing taste history."""
    status = await reroll_service.start(token)
    if status == "not-found":
        raise HTTPException(status_code=404, detail="Token not found. Please reconfigure the addon.")
    if status == "already-running":
        return {"status": "already-running", "detail": "A recommendation reroll is already in progress."}
    return {
        "status": "started",
        "detail": (
            "Current recommendation batches are being excluded and replaced with fresh alternatives. "
            "The existing Nuvio For You collection will be reconciled when the reroll finishes."
        ),
    }
