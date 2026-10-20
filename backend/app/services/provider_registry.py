"""Provider and route registry re-exports."""

from app.services.route_registry import (  # noqa: F401
    DEFAULT_ROUTE_ID,
    DEFAULT_ROUTE_MODELS,
    DIRECT_PROVIDERS,
    OAUTH_PROVIDER_LABELS,
    OAUTH_PROVIDERS,
    compute_oauth_proxy_prefix,
    ensure_model_belongs_to_route,
    format_route_model_id,
    is_route_model_id,
    map_legacy_model_to_route,
    normalize_legacy_provider_id,
    parse_route_model_id,
    provider_to_route_id,
    resolve_active_route_id,
    seed_oauth_routes,
    seed_oauth_routes_sync,
    validate_model_for_route,
)
