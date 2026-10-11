import httpx

from artemis.a2a.client import A2AClient
from artemis.a2a.server import build_app
from artemis.config import Settings
from artemis.db import create_db_engine, make_session_factory
from artemis.db.migrations import bootstrap
from artemis.services.runtime import Runtime


def _runtime(tmp_path) -> Runtime:
    engine = create_db_engine(f"sqlite+libsql:///{tmp_path / 'artemis.db'}")
    bootstrap(engine, "owner", "Owner")
    return Runtime(
        settings=Settings(owner_id="owner", a2a_public_url="http://test", agent_home=tmp_path),
        engine=engine,
        session_factory=make_session_factory(engine),
    )


async def test_healthz_ok(tmp_path):
    runtime = _runtime(tmp_path)
    app = build_app(runtime.settings, runtime=runtime, registry=None, a2a_client=A2AClient())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
