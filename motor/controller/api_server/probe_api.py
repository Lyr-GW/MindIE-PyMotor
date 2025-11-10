#!/usr/bin/env python3
# coding=utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

from fastapi import APIRouter

router = APIRouter()


@router.get("/startup")
async def startup():
    return {"message": "Controller startup"}


@router.get("/readiness")
async def readiness():
    return {"message": "Controller readiness"}


@router.get("/liveness")
async def liveness():
    return {"message": "Controller liveness"}

