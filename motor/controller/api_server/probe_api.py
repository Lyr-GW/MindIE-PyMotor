# coding=utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

from fastapi import APIRouter, HTTPException

from motor.common.standby.standby_manager import StandbyRole

router = APIRouter()


@router.get("/startup")
async def startup():
    return {"message": "Controller startup"}


@router.get("/readiness")
async def readiness():
    """
    Readiness probe - returns result base on deploy mode and role:

    STANDALONE: returns 200 if overall healthy.
                Otherwise, returns 503.

    MASTER_STANDBY: returns 200 only when role is master and overall healthy.
                    Otherwise, returns 503.
    
    """
    from motor.controller.main import get_controller_status
    status = get_controller_status()
    if status.get("overall_healthy") is False:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Controller is not ready",
                "reason": "Overall not healthy"
            }
        )

    if status.get("deploy_mode") == "master_standby":
        if status.get("role") != StandbyRole.MASTER.value:
            raise HTTPException(
                status_code=503,
                detail={
                    "message": "Controller is not ready",
                    "reason": "Not master"
                }
            )
    return {"message": "Controller is ready"}


@router.get("/liveness")
async def liveness():
    """Liveness probe - returns 200 as long as the process is running"""
    from motor.controller.main import get_controller_status
    status = get_controller_status()

    # For liveness, we just check if the process is responsive
    # Even standby controllers should be considered alive
    if status.get("overall_healthy") is False:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Controller is not alive",
                "reason": "Overall not healthy"
            }
        )
    else:
        return {"message": "Controller is alive"}

