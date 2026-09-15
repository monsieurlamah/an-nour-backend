"""A user can be created without an email — the super-admin generates a
unique identifiant instead, and login accepts either credential
interchangeably. See UserService.generate_identifiant / get_by_login and
AuthService.authenticate."""

import pytest
from pydantic import ValidationError

from app.modules.auth.services import AuthService
from app.modules.users.schemas import UserCreate
from app.modules.users.services import UserService


async def test_create_without_email_generates_identifiant(db):
    created = await UserService(db).create(
        UserCreate(firstname="Mamadou", lastname="Diallo", password="Abcdef1!")
    )

    assert created.email is None
    assert created.identifiant == "mamadou-diallo"


async def test_identifiant_collision_gets_suffixed(db):
    first = await UserService(db).create(
        UserCreate(firstname="Mamadou", lastname="Diallo", password="Abcdef1!")
    )
    second = await UserService(db).create(
        UserCreate(firstname="Mamadou", lastname="Diallo", password="Abcdef1!")
    )

    assert first.identifiant == "mamadou-diallo"
    assert second.identifiant == "mamadou-diallo-2"


async def test_login_accepts_identifiant_or_email(db):
    created = await UserService(db).create(
        UserCreate(
            firstname="Awa", lastname="Sanssoucis", email="awa.sanssoucis@example.com",
            password="Abcdef1!",
        )
    )
    created.email_verified = True
    db.add(created)
    await db.flush()

    by_identifiant = await AuthService(db).login(created.identifiant, "Abcdef1!")
    assert by_identifiant.access_token

    by_email = await AuthService(db).login("awa.sanssoucis@example.com", "Abcdef1!")
    assert by_email.access_token

    # Case-insensitive on both fields.
    by_identifiant_upper = await AuthService(db).login(created.identifiant.upper(), "Abcdef1!")
    assert by_identifiant_upper.access_token


async def test_login_without_email_works_with_identifiant_only(db):
    created = await UserService(db).create(
        UserCreate(firstname="Ibrahima", lastname="Sansmail", password="Abcdef1!")
    )
    created.email_verified = True
    db.add(created)
    await db.flush()

    token = await AuthService(db).login(created.identifiant, "Abcdef1!")
    assert token.access_token


def test_send_credentials_requires_email():
    with pytest.raises(ValidationError, match="adresse e-mail"):
        UserCreate(
            firstname="Sans", lastname="Email", password="Abcdef1!", send_credentials=True
        )
