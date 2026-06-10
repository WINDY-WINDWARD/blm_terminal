import re

with open('backend/app/mcp_server.py', 'r') as f:
    content = f.read()

# 1. Add current_user_id import and helper functions at the beginning of Watchlist Endpoints
helper_code = """# Watchlist Endpoints
# ---------------------------------------------------------------------------

from app.auth import current_user_id

async def _get_user_id_or_default() -> int:
    uid = current_user_id.get()
    return uid if uid is not None else 1

async def _get_default_watchlist_id(db) -> int:
    from sqlalchemy import select
    user_id = await _get_user_id_or_default()
    q = select(WatchlistModel).where(WatchlistModel.user_id == user_id, WatchlistModel.name == "Default")
    wl = (await db.execute(q)).scalar_one_or_none()
    if wl:
        return wl.id
    wl = WatchlistModel(name="Default", user_id=user_id)
    db.add(wl)
    await db.commit()
    await db.refresh(wl)
    return wl.id
"""
content = content.replace("# Watchlist Endpoints\n# ---------------------------------------------------------------------------\n", helper_code)


# 2. list_watchlist
old_list_watchlist = """async def list_watchlist() -> dict[str, Any]:
    \"\"\"List all items in the default watchlist (ID 1), ordered by time added.

    Each item contains: id, symbol, exchange, createdAt.
    \"\"\"
    async with AsyncSessionLocal() as db:
        q = select(WatchlistItemModel).order_by(WatchlistItemModel.created_at)
        res = await db.execute(q)"""
new_list_watchlist = """async def list_watchlist() -> dict[str, Any]:
    \"\"\"List all items in the user's default watchlist, ordered by time added.

    Each item contains: id, symbol, exchange, createdAt.
    \"\"\"
    async with AsyncSessionLocal() as db:
        wl_id = await _get_default_watchlist_id(db)
        q = select(WatchlistItemModel).where(WatchlistItemModel.watchlist_id == wl_id).order_by(WatchlistItemModel.created_at)
        res = await db.execute(q)"""
content = content.replace(old_list_watchlist, new_list_watchlist)

# 3. get_watchlist_symbols
old_get_symbols = """async def get_watchlist_symbols() -> dict[str, Any]:
    \"\"\"Fetch distinct symbols from the default watchlist as a flat list.\"\"\"
    async with AsyncSessionLocal() as db:
        q = select(WatchlistItemModel.symbol).distinct().order_by(WatchlistItemModel.symbol)"""
new_get_symbols = """async def get_watchlist_symbols() -> dict[str, Any]:
    \"\"\"Fetch distinct symbols from the user's default watchlist as a flat list.\"\"\"
    async with AsyncSessionLocal() as db:
        wl_id = await _get_default_watchlist_id(db)
        q = select(WatchlistItemModel.symbol).where(WatchlistItemModel.watchlist_id == wl_id).distinct().order_by(WatchlistItemModel.symbol)"""
content = content.replace(old_get_symbols, new_get_symbols)

# 4. remove_watchlist_item
old_remove = """        item = await db.get(WatchlistItemModel, item_id)
        if item is None:
            raise ValueError(f"watchlist item {item_id} not found")"""
new_remove = """        item = await db.get(WatchlistItemModel, item_id)
        if item is None:
            raise ValueError(f"watchlist item {item_id} not found")
        watchlist = await db.get(WatchlistModel, item.watchlist_id)
        user_id = await _get_user_id_or_default()
        if watchlist is None or watchlist.user_id != user_id:
            raise ValueError(f"watchlist item {item_id} not found")"""
content = content.replace(old_remove, new_remove)

# 5. list_watchlists
old_list_watchlists = """    async with AsyncSessionLocal() as db:
        stmt = (
            select(
                WatchlistModel.id,
                WatchlistModel.name,
                WatchlistModel.created_at,
                func.count(WatchlistItemModel.id).label("item_count"),
            )
            .outerjoin(WatchlistItemModel, WatchlistItemModel.watchlist_id == WatchlistModel.id)
            .group_by(WatchlistModel.id)
            .order_by(WatchlistModel.id)
        )"""
new_list_watchlists = """    async with AsyncSessionLocal() as db:
        user_id = await _get_user_id_or_default()
        stmt = (
            select(
                WatchlistModel.id,
                WatchlistModel.name,
                WatchlistModel.created_at,
                func.count(WatchlistItemModel.id).label("item_count"),
            )
            .outerjoin(WatchlistItemModel, WatchlistItemModel.watchlist_id == WatchlistModel.id)
            .where(WatchlistModel.user_id == user_id)
            .group_by(WatchlistModel.id)
            .order_by(WatchlistModel.id)
        )"""
content = content.replace(old_list_watchlists, new_list_watchlists)

# 6. get_watchlist_items
old_get_items = """        watchlist = await db.get(WatchlistModel, watchlist_id)
        if watchlist is None:
            raise ValueError(f"Watchlist {watchlist_id} not found")"""
new_get_items = """        user_id = await _get_user_id_or_default()
        watchlist = await db.get(WatchlistModel, watchlist_id)
        if watchlist is None or watchlist.user_id != user_id:
            raise ValueError(f"Watchlist {watchlist_id} not found")"""
content = content.replace(old_get_items, new_get_items)

# 7. create_watchlist
old_create = """        watchlist = WatchlistModel(name=name)
        db.add(watchlist)"""
new_create = """        user_id = await _get_user_id_or_default()
        watchlist = WatchlistModel(name=name, user_id=user_id)
        db.add(watchlist)"""
content = content.replace(old_create, new_create)

# 8. add_watchlist_item
old_add_item = """    async with AsyncSessionLocal() as db:
        watchlist = await db.get(WatchlistModel, watchlist_id)
        if watchlist is None:
            raise ValueError(f"Watchlist {watchlist_id} not found")"""
new_add_item = """    async with AsyncSessionLocal() as db:
        user_id = await _get_user_id_or_default()
        watchlist = await db.get(WatchlistModel, watchlist_id)
        if watchlist is None or watchlist.user_id != user_id:
            raise ValueError(f"Watchlist {watchlist_id} not found")"""
content = content.replace(old_add_item, new_add_item)

# 9. bulk_replace_watchlist
old_bulk_replace = """    async with AsyncSessionLocal() as db:
        watchlist = await db.get(WatchlistModel, watchlist_id)
        if watchlist is None:
            raise ValueError(f"Watchlist {watchlist_id} not found")"""
new_bulk_replace = """    async with AsyncSessionLocal() as db:
        user_id = await _get_user_id_or_default()
        watchlist = await db.get(WatchlistModel, watchlist_id)
        if watchlist is None or watchlist.user_id != user_id:
            raise ValueError(f"Watchlist {watchlist_id} not found")"""
content = content.replace(old_bulk_replace, new_bulk_replace)

# 10. get_notifications
old_get_notif = """    async with AsyncSessionLocal() as db:
        stmt = (
            select(Notification)
            .where(Notification.watchlist_id == watchlist_id)"""
new_get_notif = """    async with AsyncSessionLocal() as db:
        user_id = await _get_user_id_or_default()
        from app.models.watchlist import Watchlist as WatchlistModel
        wl = await db.get(WatchlistModel, watchlist_id)
        if wl is None or wl.user_id != user_id:
            raise ValueError("Watchlist not found")

        stmt = (
            select(Notification)
            .where(Notification.watchlist_id == watchlist_id)"""
content = content.replace(old_get_notif, new_get_notif)

with open('backend/app/mcp_server.py', 'w') as f:
    f.write(content)

print('Patched successfully!')
