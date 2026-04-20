import asyncio
import httpx
from uuid6 import uuid7
from tortoise import Tortoise
import os
from dotenv import load_dotenv
from models import Profile

load_dotenv()

SEED_URL = "https://drive.google.com/file/d/1Up06dcS9OfUEnDj_u6OV_xTRntupFhPH/view"
DATABASE_URL = os.getenv("DATABASE_URL")

async def seed_database():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set")
    
    #for tortoise
    if DATABASE_URL.startswith("postgresql://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgres://", 1)
    if DATABASE_URL.startswith("postgresql+asyncpg://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgres://", 1)
        await Tortoise.init(
            db_url=DATABASE_URL, 
            modules={"models": ["models"]}
        )
        await Tortoise.generate_schemas()

        print("Fetching seed data....")
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                response = await client.get(SEED_URL)
                response.raise_for_status()
                data = response.json()
            except httpx.RequestError as e:
                print(f"Failed to fetch seed data: {e}")
                return
            except httpx.HTTPStatusError as e:
                print(f"HTTP error while fetching seed data: {e}")
                return
            except Exception as e:
                print(f"Unexpected error: {e}")
                return
            profiles = data.get("profiles", [])
            created= 0
            skipped = 0
            for profile in profiles:
                exists = await Profile.filter(name=profile["name"]).first()
                if exists:
                    skipped += 1
                    continue
                await Profile.create(
                    id=uuid7(),
                    name=profile["name"],
                    gender=profile["gender"],
                    gender_probability=profile["gender_probability"],
                    age=profile["age"],
                    age_group=profile["age_group"],
                    country_id=profile["country_id"],
                    country_name=profile["country_name"],
                    country_probability=profile["country_probability"],
                )
                created += 1

    print(f"Done. Created: {created}, Skipped: {skipped}")
    await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(seed_database())