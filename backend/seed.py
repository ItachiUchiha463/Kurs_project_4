"""Початкові дані: базові правила виведення. Безпечно запускати повторно (оновлює за назвою)."""
import asyncio

from sqlalchemy import select

from app.db import SessionLocal, engine
from app.models import Rule
from app.seed_rules import BASE_RULES


async def seed_rules(db) -> None:
    existing = {r.name: r for r in await db.scalars(select(Rule).where(Rule.owner_id.is_(None)))}
    for data in BASE_RULES:
        rule = existing.get(data["name"])
        if rule:
            for k, v in data.items():
                setattr(rule, k, v)
        else:
            db.add(Rule(owner_id=None, **data))


async def main() -> None:
    async with SessionLocal() as db:
        await seed_rules(db)
        await db.commit()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
