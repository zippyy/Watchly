import asyncio
from typing import Any

from loguru import logger

from app.core.constants import REROLL_LOCK_KEY
from app.core.security import redact_token
from app.services.manifest import manifest_service
from app.services.nuvio_collection_sync import reconcile_existing_nuvio_collection
from app.services.recommendation.catalog_service import catalog_service
from app.services.redis_service import redis_service
from app.services.token_store import token_store
from app.services.user_cache import user_cache

REROLL_LOCK_TTL_SECONDS = 30 * 60
REROLL_CONCURRENCY = 3


class RerollService:
    """Replace currently served recommendations while keeping the current taste profile."""

    def __init__(self) -> None:
        self._pending_tasks: set[asyncio.Task] = set()

    def _on_task_done(self, task: asyncio.Task) -> None:
        self._pending_tasks.discard(task)
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return
        if exc is not None:
            logger.error(f"Recommendation reroll task crashed ({type(exc).__name__})")

    async def start(self, token: str) -> str:
        token = await token_store.resolve_alias(token)
        credentials = await token_store.get_user_data(token)
        if not credentials:
            return "not-found"

        lock_key = REROLL_LOCK_KEY.format(token=token)
        if not await redis_service.set_nx(lock_key, "1", REROLL_LOCK_TTL_SECONDS):
            return "already-running"

        task = asyncio.create_task(self._run(token, lock_key))
        self._pending_tasks.add(task)
        task.add_done_callback(self._on_task_done)
        return "started"

    async def _run(self, token: str, lock_key: str) -> None:
        try:
            manifest = await manifest_service.get_manifest_for_token(token)
            catalogs = [
                (catalog.get("type"), catalog.get("id"))
                for catalog in manifest.get("catalogs", [])
                if catalog.get("type") in {"movie", "series"} and catalog.get("id")
            ]

            current_rows = await asyncio.gather(
                *(user_cache.get_catalog(token, content_type, catalog_id) for content_type, catalog_id in catalogs)
            )
            exclusions: dict[str, dict[str, set[str]]] = {"movie": {}, "series": {}}
            for (content_type, catalog_id), current in zip(catalogs, current_rows, strict=True):
                current_metas = current[0].get("metas", []) if current else []
                exclusions[content_type][catalog_id] = {
                    item["id"]
                    for item in current_metas
                    if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].startswith("tt")
                }

            await user_cache.set_reroll_exclusions(token, exclusions)

            semaphore = asyncio.Semaphore(REROLL_CONCURRENCY)

            async def reroll_one(content_type: str, catalog_id: str) -> dict[str, Any]:
                async with semaphore:
                    current_ids = exclusions[content_type][catalog_id]
                    await user_cache.invalidate_catalog(token, content_type, catalog_id)
                    data, _ = await catalog_service.get_catalog(
                        token,
                        content_type,
                        catalog_id,
                        trigger_auto_update=False,
                    )
                    new_ids = {
                        item["id"]
                        for item in data.get("metas", [])
                        if isinstance(item, dict) and isinstance(item.get("id"), str)
                    }
                    return {
                        "type": content_type,
                        "id": catalog_id,
                        "previous": len(current_ids),
                        "new": len(new_ids),
                        "overlap": len(current_ids & new_ids),
                    }

            results = await asyncio.gather(
                *(reroll_one(content_type, catalog_id) for content_type, catalog_id in catalogs),
                return_exceptions=True,
            )

            failures = 0
            for result in results:
                if isinstance(result, Exception):
                    failures += 1
                    logger.warning(f"[{redact_token(token)}] Catalog reroll failed ({type(result).__name__})")

            try:
                nuvio_result = await reconcile_existing_nuvio_collection(token, manifest)
                logger.debug(f"[{redact_token(token)}] Nuvio collection reroll reconcile: {nuvio_result}")
            except Exception as exc:
                logger.warning(f"[{redact_token(token)}] Nuvio collection reroll sync failed ({type(exc).__name__})")

            logger.info(
                f"[{redact_token(token)}] Recommendation reroll complete: "
                f"{len(catalogs) - failures}/{len(catalogs)} catalogs rebuilt"
            )
        finally:
            await redis_service.delete(lock_key)


reroll_service = RerollService()
