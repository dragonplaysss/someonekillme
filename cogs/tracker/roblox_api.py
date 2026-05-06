import aiohttp
import asyncio

class RobloxAPI:
    def __init__(self):
        self.session = aiohttp.ClientSession()

    async def safe_request(self, method, url, **kwargs):
        for _ in range(3):
            try:
                async with self.session.request(method, url, **kwargs) as res:
                    return await res.json()
            except:
                await asyncio.sleep(1)
        return None

    async def get_user_id(self, username):
        data = await self.safe_request(
            "POST",
            "https://users.roblox.com/v1/usernames/users",
            json={"usernames": [username]}
        )
        if data and data["data"]:
            return data["data"][0]["id"]

    async def get_presence(self, user_id):
        data = await self.safe_request(
            "POST",
            "https://presence.roblox.com/v1/presence/users",
            json={"userIds": [user_id]}
        )
        return data["userPresences"][0] if data else None

    async def get_join_link(self, place_id, job_id):
        cursor = ""

        while True:
            data = await self.safe_request(
                "GET",
                f"https://games.roblox.com/v1/games/{place_id}/servers/Public?limit=100&cursor={cursor}"
            )

            if not data:
                return None

            for server in data.get("data", []):
                if server["id"] == job_id:
                    return f"https://www.roblox.com/games/{place_id}?gameInstanceId={job_id}"

            cursor = data.get("nextPageCursor")
            if not cursor:
                break

        return None