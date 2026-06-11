"""Health check endpoint."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check():
    """Basic health check for load balancers and monitoring."""
    return {
        "status": "healthy",
        "service": "agentzline",
        "tier": "bronze",
        "version": "0.1.0",
    }


@router.get("/health/ready")
async def readiness_check():
    """Readiness probe — checks if all dependencies are available."""
    # TODO: Add DB connectivity check and external API reachability
    return {"status": "ready"}
