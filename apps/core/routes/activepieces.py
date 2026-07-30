from fastapi import APIRouter, Request, JSONResponse

from apps.core.tools.activepieces_mcp import get_activepieces_mcp
from apps.core import auth

router = APIRouter()


@router.get("/api/v1/activepieces/selftest")
async def activepieces_selftest(request: Request):
    m = get_activepieces_mcp()
    out = await m.self_test()
    return JSONResponse(out)


class ExecRequest(BaseModel):
    flow_id: str
    input: dict | None = None


@router.get("/api/v1/activepieces/flows")
async def activepieces_flows(request: Request):
    m = get_activepieces_mcp()
    flows = await m.list_flows()
    return {"count": len(flows), "flows": flows}


@router.post("/api/v1/activepieces/execute")
async def activepieces_execute(request: Request):
    user = auth.verify_user(request.cookies.get(auth.USER_COOKIE))
    if not user:
        return JSONResponse({"ok": False, "error": "auth"}, status_code=401)
    body = await request.json()
    flow_id = body.get("flow_id")
    inputs = body.get("input") or {}
    if not flow_id:
        return JSONResponse({"ok": False, "error": "flow_id required"}, status_code=400)
    m = get_activepieces_mcp()
    res = await m.execute_flow(flow_id, inputs)
    return JSONResponse(res)
