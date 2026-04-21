"""
QR code generation for printable socket labels (v3.7).

Every physical socket has a QR printed on its face pointing at the mobile
deep-link URL. This service renders 300x300 PNGs to `backend/static/qr/`
with a human-readable text label below the matrix (so operators printing
labels can verify the target without scanning).

Design constraints:
  - Idempotent on disk: `generate_socket_qr` returns the existing path if
    the file is already there. Callers that want a fresh image use the
    `/api/pedestals/{cab}/qr/regenerate` endpoint which deletes first.
  - Does NOT replace v3.6's `GET /api/mobile/socket/{pid}/{sid}/qr` —
    that endpoint streams a label-less PNG for ad-hoc previews. This
    service produces the labelled, printable variant.
  - Safe to call from MQTT handlers: every error is caught and logged;
    discovery paths must never crash on a QR-gen failure.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Iterable

import qrcode
from PIL import Image, ImageDraw, ImageFont


logger = logging.getLogger(__name__)

QR_URL_TEMPLATE = "https://marina.lika.solutions/mobile/socket/{cabinet_id}/{socket_id}"

# Resolve the target directory relative to the backend package root.
# backend/app/services/qr_service.py → backend/static/qr
_QR_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "qr"

# Label font — fall back to Pillow's default bitmap font if a TTF isn't
# available on the host. The NUC has no Noto/DejaVu guaranteed; keeping
# the dependency list honest is more important than pixel-perfect text.
_LABEL_HEIGHT_PX = 50
_IMAGE_SIZE_PX = 300


def _ensure_qr_dir() -> Path:
    _QR_DIR.mkdir(parents=True, exist_ok=True)
    return _QR_DIR


def _qr_path(cabinet_id: str, socket_id: str) -> Path:
    return _ensure_qr_dir() / f"{cabinet_id}_{socket_id}.png"


def _load_font() -> ImageFont.ImageFont:
    # Prefer a readable TTF if the platform has one; fall back to Pillow's
    # pixel font. Both produce a legible label at the size we render.
    for candidate in (
        "arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, 14)
        except OSError:
            continue
    return ImageFont.load_default()


def _render_qr_with_label(target_url: str, label_text: str) -> Image.Image:
    """Return a 300x(300+label) composite: the QR matrix above, text below."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(target_url)
    qr.make(fit=True)
    matrix = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    # Scale to exactly 300x300 so every label on the sheet is the same size.
    matrix = matrix.resize((_IMAGE_SIZE_PX, _IMAGE_SIZE_PX), Image.NEAREST)

    canvas = Image.new("RGB", (_IMAGE_SIZE_PX, _IMAGE_SIZE_PX + _LABEL_HEIGHT_PX), "white")
    canvas.paste(matrix, (0, 0))

    draw = ImageDraw.Draw(canvas)
    font = _load_font()
    # Pillow 10 removed textsize(); use textbbox for horizontal centering.
    try:
        bbox = draw.textbbox((0, 0), label_text, font=font)
        text_w = bbox[2] - bbox[0]
    except Exception:
        text_w = len(label_text) * 7  # conservative fallback
    x = max(0, (_IMAGE_SIZE_PX - text_w) // 2)
    y = _IMAGE_SIZE_PX + (_LABEL_HEIGHT_PX // 2) - 8
    draw.text((x, y), label_text, fill="black", font=font)
    return canvas


def generate_socket_qr(cabinet_id: str, socket_id: str) -> str:
    """Render + persist the labelled QR PNG for a socket.

    Idempotent: if the target file already exists, return its path without
    regenerating. Use `regenerate_socket_qr` (below) when a rewrite is wanted.
    """
    path = _qr_path(cabinet_id, socket_id)
    if path.exists():
        return str(path)

    try:
        url = QR_URL_TEMPLATE.format(cabinet_id=cabinet_id, socket_id=socket_id)
        # Label style: "MAR KRK ORM 01 — Q1" — readable on a printed sticker.
        label = f"{cabinet_id.replace('_', ' ')} — {socket_id}"
        img = _render_qr_with_label(url, label)
        img.save(path, format="PNG")
        logger.info("[QR] generated %s", path)
    except Exception as e:  # pragma: no cover — defensive for MQTT handlers
        logger.warning("[QR] failed to generate %s: %s", path, e)
    return str(path)


def regenerate_socket_qr(cabinet_id: str, socket_id: str) -> str:
    """Force-rewrite the PNG. Used by the admin regenerate endpoint."""
    path = _qr_path(cabinet_id, socket_id)
    try:
        if path.exists():
            path.unlink()
    except Exception as e:
        logger.warning("[QR] could not delete %s before regenerate: %s", path, e)
    return generate_socket_qr(cabinet_id, socket_id)


def get_socket_qr_path(cabinet_id: str, socket_id: str) -> str | None:
    """Return the file path if the PNG is on disk, else None."""
    path = _qr_path(cabinet_id, socket_id)
    return str(path) if path.exists() else None


def generate_all_qr_for_pedestal(cabinet_id: str, socket_ids: Iterable[str]) -> list[str]:
    """Generate QR PNGs for every socket on a pedestal. Called from the
    MQTT auto-discovery handler when a new cabinet is registered."""
    out: list[str] = []
    for sid in socket_ids:
        out.append(generate_socket_qr(cabinet_id, sid))
    return out


def delete_all_qr_for_pedestal(cabinet_id: str) -> int:
    """Remove every `{cabinet_id}_*.png` file. Used by the admin regenerate
    endpoint as step 1 before re-rendering. Returns the number deleted."""
    _ensure_qr_dir()
    count = 0
    try:
        for p in _QR_DIR.glob(f"{cabinet_id}_*.png"):
            try:
                p.unlink()
                count += 1
            except OSError as e:
                logger.warning("[QR] could not delete %s: %s", p, e)
    except Exception as e:
        logger.warning("[QR] delete_all_qr_for_pedestal(%s) failed: %s", cabinet_id, e)
    return count


# Exposed for the main.py startup hook and for tests that need to inspect
# the target directory without reaching into the module-private helper.
def qr_dir() -> str:
    return str(_ensure_qr_dir())


# Create the directory at import time so every worker has it ready without
# waiting for the first HTTP request. Cheap: a stat + mkdir.
_ensure_qr_dir()
