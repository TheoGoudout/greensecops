from fastapi import APIRouter
from fastapi.responses import Response

router = APIRouter(prefix="/badges", tags=["badges"])


@router.get("/{owner}/{repo}/{branch}.svg", response_class=Response)
async def get_badge(owner: str, repo: str, branch: str) -> Response:
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="20"><text y="15" font-size="12">GreenSecOps</text></svg>'
    return Response(content=svg, media_type="image/svg+xml")
