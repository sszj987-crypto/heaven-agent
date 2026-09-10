from pathlib import Path

from fastapi.testclient import TestClient

from src.main import create_app


def test_lifespan_passes_project_path_to_container_factory(tmp_path):
    received = []

    class Container:
        async def close(self):
            pass

    def build_container(root, _settings):
        received.append(root)
        return Container()

    app = create_app(build_container, project_root=tmp_path)
    with TestClient(app) as client:
        assert client.get("/").status_code == 200

    assert received == [Path(tmp_path)]
