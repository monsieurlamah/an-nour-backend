"""Business logic for the stores module."""

from app.modules.common.crud import CRUDService
from app.modules.stores.models import Store, StoreUser


class StoreService(CRUDService[Store]):
    model = Store


class StoreUserService(CRUDService[StoreUser]):
    model = StoreUser
