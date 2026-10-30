"""Public files: the Mini firmware binary and the content-addressed Mini assets."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from flask import Blueprint, Response, request, send_from_directory

from ticker.server.api.common import ApiError, application, firmware, not_found

routes = Blueprint("files", __name__)


@routes.get("/firmware/<path:filename>")
def firmware_binary(filename: str):
    """Serve only the binary of the configured Mini firmware release."""
    manifest, directory = firmware()
    if manifest is None or directory is None:
        raise not_found("firmware binary is unavailable")
    if application().repository.updates.quarantined("mini", manifest.version):
        raise ApiError("firmware release is quarantined", 409, "firmware_quarantined")
    requested = Path(filename)
    published = Path(urlparse(manifest.binary_url).path).name
    if requested.name != filename or requested.name != published or requested.suffix != ".bin" \
            or not (Path(directory) / requested.name).is_file():
        raise not_found("firmware binary is unavailable")
    return send_from_directory(Path(directory), requested.name, mimetype="application/octet-stream", conditional=True)


@routes.get("/assets/sprites/<asset_id>.mts")
def sprite(asset_id: str):
    return _immutable(application().mini_sprites, asset_id, "application/vnd.sportsticker.rgb565-mask", "sprite is unavailable")


@routes.get("/assets/artwork/<asset_id>.mta")
def artwork(asset_id: str):
    return _immutable(application().mini_artwork, asset_id, "application/vnd.sportsticker.rgb565", "artwork is unavailable")


def _immutable(service: Any, asset_id: str, mimetype: str, missing: str) -> Response:
    """Serve one asset whose ID is its content hash, so a client can keep it for a year."""
    asset = None if service is None else service.read(asset_id)
    if asset is None:
        raise not_found(missing)
    data, checksum = asset
    response = Response(data, mimetype=mimetype)
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    response.headers["X-Content-SHA256"] = checksum
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.set_etag(checksum)
    return response.make_conditional(request)
