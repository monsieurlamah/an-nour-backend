"""Idempotent database seeding.

Run with:  poetry run seed

Reconciles the database with the declarations in ``app.seeds.data``:
- permissions, groups and their links (group_permissions),
- base application settings,
- the first super-admin user (credentials from settings/.env).

Safe to run multiple times: existing rows are matched by their natural key
(slug / key / email) and created only when missing.
"""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.database.enums import UserStatus
from app.database.session import SessionLocal, dispose_engine
from app.modules.access.models import Group, GroupPermission, Permission, UserGroup
from app.modules.expenses.models import ExpenseCategory
from app.modules.system.models import Setting
from app.modules.users.models import User
from app.security.password import hash_password
from app.seeds import data

logger = get_logger("seed")


async def seed_permissions(db: AsyncSession) -> dict[str, Permission]:
    existing = {p.slug: p for p in (await db.execute(select(Permission))).scalars()}
    created = 0
    for slug, module, name in data.PERMISSIONS:
        perm = existing.get(slug)
        if perm is None:
            perm = Permission(slug=slug, module=module, name=name)
            db.add(perm)
            existing[slug] = perm
            created += 1
        else:
            perm.module, perm.name = module, name
    await db.flush()
    logger.info("Permissions: %d total (%d created).", len(existing), created)
    return existing


async def seed_groups(db: AsyncSession) -> dict[str, Group]:
    existing = {g.slug: g for g in (await db.execute(select(Group))).scalars()}
    created = 0
    for slug, name, description in data.GROUPS:
        group = existing.get(slug)
        if group is None:
            group = Group(slug=slug, name=name, description=description)
            db.add(group)
            existing[slug] = group
            created += 1
        else:
            group.name, group.description = name, description
    await db.flush()
    logger.info("Groups: %d total (%d created).", len(existing), created)
    return existing


async def seed_group_permissions(
    db: AsyncSession,
    groups: dict[str, Group],
    permissions: dict[str, Permission],
) -> None:
    existing = {
        (gp.group_id, gp.permission_id): gp
        for gp in (await db.execute(select(GroupPermission))).scalars()
    }
    created = 0
    for group_slug, perm_slugs in data.GROUP_PERMISSIONS.items():
        group = groups.get(group_slug)
        if group is None:
            logger.warning("Unknown group %r in GROUP_PERMISSIONS, skipping.", group_slug)
            continue
        resolved = permissions.values() if perm_slugs == ["*"] else [
            permissions[s] for s in perm_slugs if s in permissions
        ]
        for perm in resolved:
            if (group.id, perm.id) not in existing:
                db.add(GroupPermission(group_id=group.id, permission_id=perm.id, allowed=True))
                existing[(group.id, perm.id)] = True  # type: ignore[assignment]
                created += 1
    await db.flush()
    logger.info("Group permissions: %d created.", created)


async def seed_settings(db: AsyncSession) -> None:
    existing = {s.key: s for s in (await db.execute(select(Setting))).scalars()}
    created = 0
    for key, value, value_type, group_name in data.SETTINGS:
        setting = existing.get(key)
        if setting is None:
            db.add(Setting(key=key, value=value, value_type=value_type, group_name=group_name))
            created += 1
        else:
            setting.value_type, setting.group_name = value_type, group_name
    await db.flush()
    logger.info("Settings: %d total (%d created).", len(existing) + created, created)


async def seed_expense_categories(db: AsyncSession) -> None:
    existing = {c.slug: c for c in (await db.execute(select(ExpenseCategory))).scalars()}
    created = 0
    for name, slug, description in data.EXPENSE_CATEGORIES:
        if slug not in existing:
            db.add(ExpenseCategory(name=name, slug=slug, description=description))
            created += 1
    await db.flush()
    logger.info("Expense categories: %d total (%d created).", len(existing) + created, created)


async def seed_superadmin(db: AsyncSession, groups: dict[str, Group]) -> None:
    email = settings.FIRST_SUPERADMIN_EMAIL.lower()
    user = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()

    if user is None:
        user = User(
            email=email,
            firstname=settings.FIRST_SUPERADMIN_FIRSTNAME,
            lastname=settings.FIRST_SUPERADMIN_LASTNAME,
            password=hash_password(settings.FIRST_SUPERADMIN_PASSWORD),
            status=UserStatus.active,
            is_activated=True,
            email_verified=True,
            must_change_password=True,
        )
        db.add(user)
        await db.flush()
        logger.info("Super-admin created: %s", email)
    else:
        logger.info("Super-admin already exists: %s", email)

    super_group = groups.get("super-admin")
    if super_group is not None:
        link = (
            await db.execute(
                select(UserGroup).where(
                    UserGroup.user_id == user.id,
                    UserGroup.group_id == super_group.id,
                )
            )
        ).scalar_one_or_none()
        if link is None:
            db.add(UserGroup(user_id=user.id, group_id=super_group.id))
            logger.info("Super-admin attached to group 'super-admin'.")


async def seed() -> None:
    try:
        async with SessionLocal() as db:
            permissions = await seed_permissions(db)
            groups = await seed_groups(db)
            await seed_group_permissions(db, groups, permissions)
            await seed_settings(db)
            await seed_expense_categories(db)
            await seed_superadmin(db, groups)
            await db.commit()
        logger.info("Seed complete.")
    finally:
        # Dispose within the same event loop to avoid "Event loop is closed".
        await dispose_engine()


def main() -> None:
    """Console entrypoint (`poetry run seed`)."""
    setup_logging()
    asyncio.run(seed())


if __name__ == "__main__":
    main()
