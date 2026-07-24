"""Business logic for the clients module."""

from fastapi import HTTPException, status
from sqlalchemy import func, select

from app.core.i18n import t
from app.modules.clients.models import Client
from app.modules.clients.schemas import ClientCreate, ClientUpdate
from app.modules.common.crud import CRUDService
from app.modules.stores.models import Store
from app.utils.helpers import normalize_email, normalize_phone

_CODE_PREFIX = "CLI-"


class ClientService(CRUDService[Client]):
    model = Client

    _READ_FIELDS = (
        "id", "uuid", "status", "created_at", "updated_at",
        "code_client", "name", "prenom", "phone", "email", "address",
        "ville", "type_client", "entreprise", "notes", "plafond_credit",
        "store_id", "created_by",
    )

    @staticmethod
    def _to_dict(client: Client, store: Store | None) -> dict:
        return {
            **{k: getattr(client, k) for k in ClientService._READ_FIELDS},
            "store_name": store.name if store else (
                f"Boutique #{client.store_id}" if client.store_id is not None else None
            ),
        }

    async def enrich(self, client: Client) -> dict:
        """Attach store_name for a single client — bypasses the soft-delete
        filter on the store lookup, same rationale as CreanceService.enrich."""
        store = await self.db.get(Store, client.store_id) if client.store_id is not None else None
        return self._to_dict(client, store)

    async def list_enriched(self, **filters) -> list[dict]:
        clients = await self.list(**filters)
        ids = {c.store_id for c in clients if c.store_id is not None}
        stores: dict[int, Store] = {}
        if ids:
            result = await self.db.execute(select(Store).where(Store.id.in_(ids)))
            stores = {s.id: s for s in result.scalars().all()}
        return [
            self._to_dict(c, stores.get(c.store_id) if c.store_id is not None else None)
            for c in clients
        ]

    async def _generate_code_client(self) -> str:
        """Return the next sequential CLI-NNNNNN code (e.g. CLI-000001)."""
        result = await self.db.execute(
            select(func.max(Client.code_client)).where(
                Client.code_client.like(f"{_CODE_PREFIX}%")
            )
        )
        max_code: str | None = result.scalar_one_or_none()
        if max_code is None:
            next_num = 1
        else:
            try:
                next_num = int(max_code[len(_CODE_PREFIX):]) + 1
            except ValueError:
                next_num = 1
        return f"{_CODE_PREFIX}{next_num:06d}"

    async def _ensure_phone_available(
        self, phone: str | None, *, exclude_id: int | None = None
    ) -> str | None:
        """Normalise phone and verify it is not already taken by another active client."""
        normalized = normalize_phone(phone)
        if normalized is None:
            return None
        result = await self.db.execute(
            select(Client).where(
                Client.phone == normalized,
                Client.deleted_at.is_(None),
            )
        )
        existing = result.scalar_one_or_none()
        if existing is not None and existing.id != exclude_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=t("client_phone_taken"),
            )
        return normalized

    async def _ensure_email_available(
        self, email: str | None, *, exclude_id: int | None = None
    ) -> str | None:
        """Normalise email and verify it is not already taken by another active client."""
        normalized = normalize_email(email)
        if normalized is None:
            return None
        result = await self.db.execute(
            select(Client).where(
                Client.email == normalized,
                Client.deleted_at.is_(None),
            )
        )
        existing = result.scalar_one_or_none()
        if existing is not None and existing.id != exclude_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=t("client_email_taken"),
            )
        return normalized

    async def create(self, payload: ClientCreate, created_by: int | None = None) -> Client:
        if not payload.phone and not payload.email:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=t("client_contact_required"),
            )

        phone = await self._ensure_phone_available(payload.phone)
        email = await self._ensure_email_available(payload.email)
        code_client = await self._generate_code_client()

        client = Client(
            code_client=code_client,
            name=payload.name.strip(),
            prenom=payload.prenom.strip() if payload.prenom else None,
            phone=phone,
            email=email,
            address=payload.address,
            ville=payload.ville,
            type_client=payload.type_client,
            entreprise=payload.entreprise,
            notes=payload.notes,
            plafond_credit=payload.plafond_credit,
            store_id=payload.store_id,
            created_by=created_by,
        )
        self.db.add(client)
        await self.db.flush()
        await self.db.refresh(client)
        return client

    async def update(self, client: Client, payload: ClientUpdate) -> Client:
        data = payload.model_dump(exclude_unset=True)

        # Compute effective contact values after the update and enforce the rule.
        effective_phone = data.get("phone", client.phone)
        effective_email = data.get("email", client.email)
        if not effective_phone and not effective_email:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=t("client_contact_required"),
            )

        if "phone" in data:
            data["phone"] = await self._ensure_phone_available(
                data["phone"], exclude_id=client.id
            )
        if "email" in data:
            data["email"] = await self._ensure_email_available(
                data["email"], exclude_id=client.id
            )

        for field, value in data.items():
            setattr(client, field, value)
        self.db.add(client)
        await self.db.flush()
        await self.db.refresh(client)
        return client
