import asyncio
import httpx
from uuid6 import uuid7
from tortoise import Tortoise
import os
from dotenv import load_dotenv
from models import Profile

load_dotenv()

SEED_URL = "https://drive.google.com/uc?export=download&id=1Up06dcS9OfUEnDj_u6OV_xTRntupFhPH"


async def seed_database():
    print("=== SEED STARTED ===", flush=True)

    DATABASE_URL = os.getenv("DATABASE_URL")

    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set")

    # Normalize DB URL for Tortoise
    if DATABASE_URL.startswith("postgresql://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgres://", 1)
    elif DATABASE_URL.startswith("postgresql+asyncpg://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgres://", 1)

    # Init DB
    await Tortoise.init(
        db_url=DATABASE_URL,
        modules={"models": ["models"]}
    )

    await Tortoise.generate_schemas()

    print("Fetching seed data...", flush=True)

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.get(SEED_URL, follow_redirects=True)
            response.raise_for_status()

            # Debug response (important for Railway visibility)
            print("Response preview:", response.text[:200], flush=True)

            try:
                data = response.json()
            except Exception:
                print(" Invalid JSON from seed URL", flush=True)
                return

        except httpx.RequestError as e:
            print(f" Failed to fetch seed data: {e}", flush=True)
            return
        except httpx.HTTPStatusError as e:
            print(f" HTTP error while fetching seed data: {e}", flush=True)
            return
        except Exception as e:
            print(f" Unexpected error: {e}", flush=True)
            return

    profiles = data.get("profiles", [])

    if not profiles:
        print(" No profiles found in seed data", flush=True)
        return

    created = 0
    skipped = 0

    for profile in profiles:
        try:
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

        except Exception as e:
            print(f"Error inserting profile {profile.get('name')}: {e}", flush=True)

    print(f" Seeding completed: {created} created, {skipped} skipped.", flush=True)

    await Tortoise.close_connections()

    print("=== SEED FINISHED ===", flush=True)


if __name__ == "__main__":
    asyncio.run(seed_database())