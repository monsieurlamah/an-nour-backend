"""Image upload endpoint — delegates to Cloudinary.

Variables .env requises :
    FILE_STORAGE_BACKEND   = cloudinary
    CLOUDINARY_CLOUD_NAME  = <votre cloud name>
    CLOUDINARY_API_KEY     = <votre api key>
    CLOUDINARY_API_SECRET  = <votre api secret>
    CLOUDINARY_FOLDER      = lamahetvous   (optionnel, déjà défini)
    UPLOAD_MAX_BYTES       = 10485760      (optionnel, 10 Mo par défaut)
"""

import io
from typing import Annotated

import cloudinary
import cloudinary.uploader
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.api.deps import get_current_active_user
from app.core.config import settings
from app.modules.users.models import User

router = APIRouter(prefix="/upload", tags=["upload"])

ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp", "image/gif"}


def _init_cloudinary() -> None:
    """Configure le SDK Cloudinary à partir des variables .env.

    Lève une HTTPException 503 si les credentials sont absents.
    """
    if not settings.cloudinary_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Cloudinary n'est pas encore configuré. "
                "Renseignez CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY "
                "et CLOUDINARY_API_SECRET dans le fichier .env puis redémarrez le serveur."
            ),
        )

    cloudinary.config(
        cloud_name=settings.CLOUDINARY_CLOUD_NAME,
        api_key=settings.CLOUDINARY_API_KEY,
        api_secret=settings.CLOUDINARY_API_SECRET,
        secure=True,
    )


class UploadResponse(BaseModel):
    url: str
    public_id: str
    width: int | None = None
    height: int | None = None
    format: str | None = None
    size_bytes: int | None = None


@router.post(
    "/image",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload une image vers Cloudinary",
)
async def upload_image(
    file: Annotated[UploadFile, File(description="Image (JPEG, PNG, WebP, GIF) — max 10 Mo")],
    _current_user: Annotated[User, Depends(get_current_active_user)],
) -> UploadResponse:
    """Reçoit un fichier image, le valide, l'envoie vers Cloudinary
    et retourne l'URL sécurisée ainsi que les métadonnées."""

    _init_cloudinary()

    # ── Validation du type MIME ──
    if file.content_type not in ALLOWED_MIME:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"Format non supporté : {file.content_type!r}. "
                "Formats acceptés : JPEG, PNG, WebP, GIF."
            ),
        )

    # ── Lecture + validation de la taille ──
    content = await file.read()
    max_mb = settings.UPLOAD_MAX_BYTES // (1024 * 1024)
    if len(content) > settings.UPLOAD_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Fichier trop volumineux. Taille maximale autorisée : {max_mb} Mo.",
        )

    # ── Upload vers Cloudinary ──
    result: dict = cloudinary.uploader.upload(
        io.BytesIO(content),
        folder=settings.CLOUDINARY_FOLDER,
        resource_type="image",
        quality="auto:good",
        fetch_format="auto",
    )

    return UploadResponse(
        url=result["secure_url"],
        public_id=result["public_id"],
        width=result.get("width"),
        height=result.get("height"),
        format=result.get("format"),
        size_bytes=result.get("bytes"),
    )
