from datetime import datetime, timezone
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field
from solution_advisor.common_analyzer.domain import WorkerInstance
from solution_advisor.platforms.domain import HostAgent
from solution_advisor.platforms.service import PlatformRegistry

router = APIRouter(tags=["workers"])

class Registration(BaseModel):
    # The HostAgent is platform-neutral.  Platform admission is governed by the
    # configured package/capabilities, not by hard-coding an X5 instance here.
    instance_id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,62}$")
    worker_type: str = Field(pattern=r"^[a-z][a-z0-9-]{1,62}$")
    image_ref: str
    image_id: str
    toolchain_version: str
    platform_package_version: str
    capabilities: list[str]
    max_concurrency: int = Field(ge=1, le=32)
    agent_version: str | None = Field(default=None, max_length=64)
    candidates: list[dict] = Field(default_factory=list)

def worker_auth(request, authorization):
    if authorization != f"Bearer {request.app.state.settings.worker_registration_token}":
        raise HTTPException(403, {"code":"worker_auth_required"})

@router.post("/api/internal/workers/register")
def register(body: Registration, request: Request, authorization: str|None=Header(None)):
    worker_auth(request, authorization)
    if set(body.capabilities) - {"static_check", "compile", "board_smoke"} or not {"static_check", "compile"}.issubset(body.capabilities):
        raise HTTPException(422, {"code":"invalid_worker_capabilities"})
    session=request.app.state.session_factory()
    try:
        item=session.get(WorkerInstance, body.instance_id)
        if item is None:
            item=WorkerInstance(id=body.instance_id, worker_type=body.worker_type, image_ref=body.image_ref, image_id=body.image_id, toolchain_version=body.toolchain_version, platform_package_version=body.platform_package_version, capabilities=body.capabilities, max_concurrency=body.max_concurrency); session.add(item)
        else:
            for field, value in body.model_dump(exclude={"agent_version", "candidates"}).items():
                setattr(item, "id" if field=="instance_id" else field, value)
        item.health="READY"; item.last_error=None; item.last_heartbeat_at=datetime.now(timezone.utc).replace(tzinfo=None)
        # Registration names a HostAgent Host, not a platform.  PlatformCandidate image
        # facts remain untrusted until an administrator creates/publishes a Catalog.
        PlatformRegistry(session).register_agent(agent_id=body.instance_id, agent_version=body.agent_version,
            candidates=body.candidates or [{"image_ref": body.image_ref, "image_id": body.image_id,
                                              "toolchain_version": body.toolchain_version, "evidence": {"source": "registration"}}])
        return {"instance_id":item.id,"health":item.health,"capabilities":item.capabilities,"max_concurrency":item.max_concurrency}
    finally: session.close()

@router.post("/api/internal/workers/{instance_id}/heartbeat")
def heartbeat(instance_id:str, request:Request, authorization:str|None=Header(None)):
    worker_auth(request, authorization); session=request.app.state.session_factory()
    try:
        item=session.get(WorkerInstance,instance_id)
        if not item: raise HTTPException(404,{"code":"worker_not_registered"})
        item.last_heartbeat_at=datetime.now(timezone.utc).replace(tzinfo=None); item.health="READY"; session.commit()
        agent = session.get(HostAgent, instance_id)
        if agent:
            PlatformRegistry(session).register_agent(agent_id=instance_id, agent_version=agent.agent_version, candidates=[])
        return {"instance_id":item.id,"health":item.health}
    finally: session.close()
