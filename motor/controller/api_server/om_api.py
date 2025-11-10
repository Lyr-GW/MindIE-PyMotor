#!/usr/bin/env python3
# coding=utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

from fastapi import APIRouter, Request

from motor.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.post("/v1/alarm/coordinator")
async def alarms(request: Request):
    body = await request.json()
    logger.info(f"received alarm request: {body}")
    return {"message": "ok"}