"""Create default admin user and migrate existing data to them."""

import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import AsyncSessionLocal
from app.models.user import User
from app.models.watchlist import Watchlist
from app.models.ai_chat import ChatSession
from app.auth import get_password_hash
from sqlalchemy import select

async def migrate_data():
    async with AsyncSessionLocal() as session:
        # Create default admin user
        stmt = select(User).where(User.username == "admin")
        result = await session.execute(stmt)
        admin = result.scalar_one_or_none()
        
        if not admin:
            admin = User(
                username="admin",
                hashed_password=get_password_hash("admin"),
                is_admin=True,
            )
            session.add(admin)
            await session.commit()
            await session.refresh(admin)
            print(f"Created admin user with ID {admin.id}")
        else:
            print(f"Admin user already exists with ID {admin.id}")
            
        # Update Watchlists
        stmt = select(Watchlist).where(Watchlist.user_id == 1)
        result = await session.execute(stmt)
        watchlists = result.scalars().all()
        for w in watchlists:
            w.user_id = admin.id
            
        # Update ChatSessions
        stmt = select(ChatSession).where(ChatSession.user_id == 1)
        result = await session.execute(stmt)
        chats = result.scalars().all()
        for c in chats:
            c.user_id = admin.id
            
        await session.commit()
        print("Migrated existing data to admin user")

if __name__ == "__main__":
    asyncio.run(migrate_data())
