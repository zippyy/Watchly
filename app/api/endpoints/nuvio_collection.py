from fastapi import APIRouter, HTTPException

from app.core.security import TOKEN_PATTERN
from app.services.manifest import manifest_service
from app.services.nuvio_collection import build_nuvio_collection

router = APIRouter()


@router.get("/{token}/nuvio-collection.json")
async def nuvio_collection(token: str) -> dict:
    if not TOKEN_PATTERN.match(token):
        raise HTTPException(status_code=400, detail="Invalid token.")

    manifest = await manifest_service.get_manifest_for_token(token)
    return build_nuvio_collection(manifest)
