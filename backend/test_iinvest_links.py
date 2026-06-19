import asyncio
from app.services.iinvest_client import _iinvest_client

async def main():
    await _iinvest_client._ensure_session()
    res = await _iinvest_client.get_announcements("RELIANCE")
    if res and res.get("data"):
        print("Announcements:", res["data"][:2])
    
    res2 = await _iinvest_client.get_board_meetings("RELIANCE")
    if res2 and res2.get("data"):
        print("Board Meetings:", res2["data"][:2])
    
    await _iinvest_client.close()

asyncio.run(main())
