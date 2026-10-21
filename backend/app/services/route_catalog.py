import json

from sqlalchemy import select

from app.models.ai_provider import AIProviderCredential, AIProviderRoute
from app.services.proxy_supervisor import get_proxy_supervisor
from app.services.route_registry import compute_oauth_proxy_prefix, format_route_model_id


async def get_route_models(route_id: str, session=None) -> list[str]:
    if route_id.startswith("direct:"):
        from app.routers.ai_chat import _fetch_direct_models
        return [entry["id"] for entry in await _fetch_direct_models(route_id.split(":", 1)[1])]
    if session is None:
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as database:
            return await get_route_models(route_id, database)
    route = (await session.execute(select(AIProviderRoute).where(AIProviderRoute.id == route_id))).scalar_one_or_none()
    if route is None or not route.enabled:
        raise ValueError("Selected provider route is unavailable")
    if route.kind == "endpoint":
        return list(json.loads(route.config_json or "{}").get("models") or [])
    credentials = list((await session.execute(select(AIProviderCredential).where(
        AIProviderCredential.route_id == route_id, AIProviderCredential.enabled == True,
        AIProviderCredential.kind == "oauth",
    ))).scalars().all())
    if not credentials:
        return list(json.loads(route.config_json or "{}").get("cached_models") or [])
    supervisor = get_proxy_supervisor()
    await supervisor.ensure_started()
    management = supervisor.get_management_client()
    prefix = (route.proxy_prefix or compute_oauth_proxy_prefix(route_id)) + "/"
    models = set()
    for credential in credentials:
        name = credential.proxy_credential_name
        name = name if name.endswith(".json") else f"{name}.json"
        for model in await management.get_credential_models(name):
            if model.startswith(prefix):
                models.add(model[len(prefix):])
    return sorted(models)


async def get_route_catalog(route_id: str) -> list[dict[str, str]]:
    return [{"id": format_route_model_id(route_id, model), "label": model} for model in await get_route_models(route_id)]
