from fastapi.routing import APIRouter

from app.services.manifest import manifest_service
from app.services.nuvio_collection import build_nuvio_manifest

router = APIRouter()


@router.get("/manifest.json")
async def manifest():
    manifest = manifest_service.get_base_manifest()
    # since user is not logged in, return empty catalogs
    manifest["catalogs"] = []
    return manifest


@router.get("/{token}/manifest.json")
async def manifest_token(token: str):
    return await manifest_service.get_manifest_for_token(token)


@router.get("/{token}/nuvio-manifest.json")
async def nuvio_manifest_token(token: str):
    manifest = await manifest_service.get_manifest_for_token(token)
    return build_nuvio_manifest(manifest)
