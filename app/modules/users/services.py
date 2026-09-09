"""Business logic for the users module."""

from collections.abc import Sequence

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import t
from app.modules.access.models import UserGroup
from app.modules.stores.models import StoreUser
from app.modules.users.models import User
from app.modules.users.schemas import ChangePasswordRequest, UserCreate, UserUpdate
from app.security.password import hash_password, verify_password
from app.utils.helpers import normalize_email, normalize_phone


class UserService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, user_id: int) -> User | None:
        return await self.db.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        result = await self.db.execute(
            select(User).where(User.email == normalize_email(email))
        )
        return result.scalar_one_or_none()

    async def get_by_phone(self, phone: str) -> User | None:
        normalized = normalize_phone(phone)
        if normalized is None:
            return None
        result = await self.db.execute(select(User).where(User.phone == normalized))
        return result.scalar_one_or_none()

    async def _ensure_email_available(
        self, email: str, *, exclude_id: int | None = None
    ) -> None:
        existing = await self.get_by_email(email)
        if existing is not None and existing.id != exclude_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=t("email_taken"),
            )

    async def _ensure_phone_available(
        self, phone: str | None, *, exclude_id: int | None = None
    ) -> str | None:
        """Validate phone uniqueness and return the canonical value to store."""
        normalized = normalize_phone(phone)
        if normalized is None:
            return None
        result = await self.db.execute(select(User).where(User.phone == normalized))
        existing = result.scalar_one_or_none()
        if existing is not None and existing.id != exclude_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=t("phone_taken"),
            )
        return normalized

    async def list(
        self,
        skip: int = 0,
        limit: int = 100,
        group_id: int | None = None,
        search: str | None = None,
        store_id: int | list[int] | None = None,
    ) -> Sequence[User]:
        stmt = select(User).where(User.deleted_at.is_(None))
        if group_id is not None:
            stmt = stmt.join(UserGroup, UserGroup.user_id == User.id).where(
                UserGroup.group_id == group_id,
                UserGroup.deleted_at.is_(None),
            )
        if store_id is not None:
            # Store-scoped caller (e.g. a gérant-boutique): only users linked
            # to one of their own store(s) via StoreUser — never the whole
            # network. `.distinct()` guards against duplicate rows if a user
            # is (unusually) linked to more than one store within scope.
            stmt = stmt.join(StoreUser, StoreUser.user_id == User.id).where(
                StoreUser.deleted_at.is_(None),
                StoreUser.store_id.in_(store_id) if isinstance(store_id, list)
                else StoreUser.store_id == store_id,
            ).distinct()
        if search:
            pattern = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    User.firstname.ilike(pattern),
                    User.lastname.ilike(pattern),
                    User.email.ilike(pattern),
                )
            )
        result = await self.db.execute(
            stmt.order_by(User.id).offset(skip).limit(limit)
        )
        return result.scalars().all()

    async def create(self, payload: UserCreate) -> User:
        email = normalize_email(str(payload.email))
        await self._ensure_email_available(email)
        phone = await self._ensure_phone_available(payload.phone)
        user = User(
            firstname=payload.firstname,
            lastname=payload.lastname,
            email=email,
            phone=phone,
            address=payload.address,
            avatar=payload.avatar,
            password=hash_password(payload.password),
            status=payload.status,
            is_activated=payload.is_activated,
        )
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def update(self, user: User, payload: UserUpdate) -> User:
        data = payload.model_dump(exclude_unset=True)
        if "password" in data:
            password = data.pop("password")
            if password:
                user.password = hash_password(password)
        if "email" in data and data["email"] is not None:
            data["email"] = normalize_email(str(data["email"]))
            await self._ensure_email_available(data["email"], exclude_id=user.id)
        if "phone" in data:
            data["phone"] = await self._ensure_phone_available(
                data["phone"], exclude_id=user.id
            )
        for field, value in data.items():
            setattr(user, field, value)
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def change_own_password(self, user: User, payload: ChangePasswordRequest) -> None:
        # First login: the account is flagged ``must_change_password`` and the
        # user just authenticated with the temporary password — no need to ask
        # for it again. Any other time, the current password must be verified.
        if not user.must_change_password:
            if not payload.current_password or not verify_password(
                payload.current_password, user.password
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=t("incorrect_current_password"),
                )
        user.password = hash_password(payload.new_password)
        user.must_change_password = False
        self.db.add(user)
        await self.db.flush()

    async def soft_delete(self, user: User) -> None:
        from app.utils.helpers import utcnow

        user.deleted_at = utcnow()
        self.db.add(user)
        await self.db.flush()
