#!/usr/bin/env python3
# coding=utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

from motor.common.resources.http_msg_spec import InsEventMsg
from motor.common.utils.http_client import SafeHTTPSClient
from motor.common.utils.logger import get_logger


logger = get_logger(__name__)


class CoordinatorApiClient:

    @staticmethod
    def send_instance_refresh(base_url: str, event_msg: InsEventMsg) -> bool:
        is_succeed = True

        try:
            client = SafeHTTPSClient(
                base_url=base_url,
                timeout=0.5
            )
            response = client.post("/instances/refresh", data=event_msg.model_dump())
            response_text = response.get("text")

            if event_msg.instances and len(event_msg.instances) > 0:
                job_name = event_msg.instances[0].job_name
                logger.info("Event pushed type: %s, job name: %s, response: %s",
                           event_msg.event, job_name, response_text)
            else:
                logger.info("Event pushed type: %s, push all instances, response: %s",
                           event_msg.event, response_text)
        except Exception as e:
            is_succeed = False
            logger.error("Exception occurred while pushing event: %s", e)
        finally:
            client.close()

        return is_succeed
