# coding=utf-8
# Copyright (c) 2025, HUAWEI CORPORATION.  All rights reserved.

import time
import queue
import threading
from dataclasses import dataclass

from motor.config.controller import ControllerConfig
from motor.common.resources.instance import Instance, ReadOnlyInstance
from motor.common.resources.http_msg_spec import InsEventMsg, EventType
from motor.common.utils.http_client import SafeHTTPSClient
from motor.common.utils.logger import get_logger
from motor.controller.core import Observer, ObserverEvent
from motor.controller.api_client.coordinator_api_client import CoordinatorApiClient


logger = get_logger(__name__)


@dataclass
class Event:
    event_type: EventType
    instance: Instance | None


class EventPusher(Observer):
    def __init__(self, config: ControllerConfig | None = None) -> None:
        super().__init__()
        # Use default config if not provided
        if config is None:
            config = ControllerConfig()

        self.is_coordinator_reset = False
        self.is_first_heartbeat_success = False  # Track if we've ever successfully connected to coordinator
        self.event_queue = queue.Queue()
        self.instances: dict[str, Instance] = {}
        self.lock = threading.Lock()
        self.config_lock = threading.RLock()
        self.stop_event = threading.Event()

        # Extract required config fields
        with self.config_lock:
            self.coordinator_api_dns = config.api_config.coordinator_api_dns
            self.coordinator_api_port = config.api_config.coordinator_api_port
            self.event_consumer_sleep_interval = config.event_config.event_consumer_sleep_interval
            self.coordinator_heartbeat_interval = config.event_config.coordinator_heartbeat_interval

        with self.config_lock:
            self.base_url = f"http://{self.coordinator_api_dns}:{self.coordinator_api_port}"
            logger.info("Coordinator API URL: %s", self.base_url)

            self.heart_client = SafeHTTPSClient(
                base_url=self.base_url,
                cert_file=None,
                key_file=None,
                ca_file=None,
                timeout=0.5
            )

        self.event_consumer_thread = None
        self.heartbeat_detector_thread = None

        logger.info("EventPusher initialized.")

    def update(self, instance: ReadOnlyInstance, event: ObserverEvent) -> None:
        # Event pusher will interact with coordinator and send instances.
        # So it should just use Instance instead of ReadOnlyInstance.
        if event == ObserverEvent.INSTANCE_ADDED:
            with self.lock:
                self.instances[instance.job_name] = instance
            # Deep copy the instance to ensure data consistency during async HTTP sending
            event = Event(EventType.ADD, instance.to_instance())
            logger.info("Instance added: %s", instance.job_name)
        elif event == ObserverEvent.INSTANCE_SEPERATED:
            with self.lock:
                if instance.job_name in self.instances:
                    del self.instances[instance.job_name]
            # Deep copy the instance to ensure data consistency during async HTTP sending
            event = Event(EventType.DEL, instance.to_instance())
            logger.info("Instance removed: %s", instance.job_name)
        elif event == ObserverEvent.INSTANCE_REMOVED:
            # Separated event is already notified coordinator
            # to remove instance. so we don't need to notify again.
            return
        else:
            raise ValueError(f"Unknown event type: {event}")

        self.event_queue.put(event)

    def start(self) -> None:
        """Start the event pusher threads"""
        # Reset stop_event if it was previously set (for singleton reuse)
        if self.stop_event.is_set():
            self.stop_event.clear()

        # Create event pusher threads
        self.event_consumer_thread = threading.Thread(
            target=self._event_consumer,
            daemon=True,
            name="EventConsumer"
        )
        self.heartbeat_detector_thread = threading.Thread(
            target=self._coordinator_heartbeat_detector,
            daemon=True,
            name="HeartbeatDetector"
        )

        self.event_consumer_thread.start()
        self.heartbeat_detector_thread.start()
        logger.info("EventPusher started.")

    def stop(self) -> None:
        self.stop_event.set()
        if self.event_queue.qsize() == 0:
            # Put a element into queue to make thread exit.
            self.event_queue.put(None)
        # Only join threads that have been started
        if self.event_consumer_thread.is_alive():
            self.event_consumer_thread.join()
        if self.heartbeat_detector_thread.is_alive():
            self.heartbeat_detector_thread.join()
        self.heart_client.close()
        logger.info("EventPusher stopped.")

    def is_alive(self) -> bool:
        """Check if the event_pusher threads are alive"""
        return (
            (self.event_consumer_thread is not None and self.event_consumer_thread.is_alive())
            and (self.heartbeat_detector_thread is not None and self.heartbeat_detector_thread.is_alive())
        )

    def update_config(self, config: ControllerConfig) -> None:
        """Update configuration for the event pusher"""
        with self.config_lock:
            # Update config fields
            self.coordinator_api_dns = config.api_config.coordinator_api_dns
            self.coordinator_api_port = config.api_config.coordinator_api_port
            self.event_consumer_sleep_interval = config.event_config.event_consumer_sleep_interval
            self.coordinator_heartbeat_interval = config.event_config.coordinator_heartbeat_interval

            # Update base URL and HTTP client if API config changed
            self.base_url = f"http://{self.coordinator_api_dns}:{self.coordinator_api_port}"
            self.heart_client = SafeHTTPSClient(
                base_url=self.base_url,
                cert_file=None,
                key_file=None,
                ca_file=None,
                timeout=0.5
            )
            logger.info("EventPusher configuration updated, new coordinator URL: %s", self.base_url)

    def _event_consumer(self) -> None:
        while not self.stop_event.is_set():
            event = self.event_queue.get()
            if event is not None:
                event_type = event.event_type
                if event_type == EventType.ADD:
                    event_msg = InsEventMsg(event=event_type, instances=[event.instance])
                elif event_type == EventType.DEL:
                    event_msg = InsEventMsg(event=event_type, instances=[event.instance])
                elif event_type == EventType.SET:
                    with self.lock:
                        instances = list(self.instances.values())
                        # Check if we have at least one prefill and one decode instance
                        has_prefill = any(inst.role == "prefill" for inst in instances)
                        has_decode = any(inst.role == "decode" for inst in instances)

                        if has_prefill and has_decode:
                            event_msg = InsEventMsg(
                                event=event_type,
                                instances=[instance.to_instance() for instance in instances]
                            )
                        else:
                            logger.debug("SET event skipped: requires at least one prefill and one "
                                         "decode instance, current instances: prefill=%s, decode=%s",
                                         has_prefill, has_decode)
                            event_msg = None
                else:
                    logger.error("Unknown event type: %s", event_type)
                    continue

                if event_msg is not None:
                    CoordinatorApiClient.send_instance_refresh(self.base_url, event_msg)

            with self.config_lock:
                sleep_interval = self.event_consumer_sleep_interval
            time.sleep(sleep_interval)

    def _coordinator_heartbeat_detector(self) -> None:
        """detect coordinator heartbeat"""
        hb_loss_cnt = 0
        log_counter = 0  # Counter to control log frequency
        log_interval = 10  # Only log every 10 iterations

        while not self.stop_event.is_set():
            try:
                response = self.heart_client.get("/readiness", params={"status": "normal"})
                # Mark that we've successfully connected to coordinator at least once
                if not self.is_first_heartbeat_success:
                    self.is_first_heartbeat_success = True
                    logger.info("Coordinator heartbeat established successfully.")
                    log_counter = 0  # Reset counter on successful connection
                if self.is_coordinator_reset:
                    # SET event means push all instances to coordinator,
                    # so job_name is not a instance job_name, it is "coordinator_restart".
                    event = Event(EventType.SET, None)
                    self.event_queue.put(event)
                    self.is_coordinator_reset = False
                    hb_loss_cnt = 0
                else:
                    if response is None or response.get("ready") is None or not response.get("ready"):
                        # When coordinator is not ready, controller will reset coordinator,
                        logger.info("Coordinator is not ready.")
                        self.is_coordinator_reset = True

            except Exception as e:
                # Only count heartbeat loss after we've successfully connected at least once
                if self.is_first_heartbeat_success:
                    hb_loss_cnt += 1
                    if hb_loss_cnt >= 2:
                        self.is_coordinator_reset = True
                        logger.warning("Coordinator heartbeat lost. Possible restart detected.")
                        hb_loss_cnt = 0
                    # Only log heartbeat failure periodically to avoid spam
                    log_counter += 1
                    if log_counter >= log_interval:
                        logger.warning("Send Coordinator heartbeat failed, Exception occurred %s", e)
                        log_counter = 0
                else:
                    # Only log waiting message periodically to avoid spam
                    log_counter += 1
                    if log_counter >= log_interval:
                        logger.info("Coordinator not yet available, waiting for first successful heartbeat.")
                        log_counter = 0

            with self.config_lock:
                heartbeat_interval = self.coordinator_heartbeat_interval
            time.sleep(heartbeat_interval)