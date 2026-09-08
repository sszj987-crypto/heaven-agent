from fastapi import Request

from ..services.container import ApplicationContainer


MAX_TEXT_IMPORT_BYTES = 5 * 1024 * 1024
MAX_AUDIO_UPLOAD_BYTES = 25 * 1024 * 1024


def get_container(request: Request) -> ApplicationContainer:
    return request.app.state.container
