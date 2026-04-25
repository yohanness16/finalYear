"""Seed Addis Ababa route and stop data into the configured database."""

import asyncio

from app.db.session import AsyncSessionLocal
from app.seeds.addis_ababa_routes import seed_addis_ababa_routes


async def main() -> None:
    """Run Addis Ababa route seeding in a single DB session."""
    async with AsyncSessionLocal() as db:
        try:
            await seed_addis_ababa_routes(db)
            print("Addis Ababa routes seeded successfully.")
        except Exception:
            await db.rollback()
            raise


if __name__ == "__main__":
    asyncio.run(main())
