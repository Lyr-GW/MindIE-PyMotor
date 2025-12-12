# coding=utf-8
# Copyright (c) 2025, HUAWEI CORPORATION.  All rights reserved.

import json
import os
import threading
from typing import Any, Type, TypeVar
from contextlib import contextmanager
from etcd3gw.client import Etcd3Client as Etcd3GwClient
from etcd3gw.lease import Lease
from etcd3gw.lock import Lock
from pydantic import BaseModel

from motor.common.utils.logger import get_logger


logger = get_logger(__name__)

T = TypeVar('T', bound=BaseModel)

namespace = os.getenv("POD_NAMESPACE")


class EtcdClient:
    """Etcd client with lease lock management and JSON data storage"""

    def __init__(
        self,
        host: str = 'localhost',
        port: int = 2379,
        ca_cert: str | None = None,
        cert_key: str | None = None,
        cert_cert: str | None = None,
        timeout: int = 5
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

        kwargs = {'host': host, 'port': port, 'timeout': timeout}
        if ca_cert and cert_key and cert_cert:
            kwargs.update({
                'ca_cert': ca_cert,
                'cert_key': cert_key,
                'cert_cert': cert_cert,
                "protocol": "https"
            })

        self.client = Etcd3GwClient(**kwargs)
        self._leases: dict[str, Lease] = {}
        self._lock = threading.Lock()

        logger.info("EtcdClient initialized with host=%s:%d", host, port)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    @staticmethod
    def get_key_with_namespace(key: str) -> str:
        return namespace + key

    def acquire_lock(self, lock_key: str, ttl: int = 30) -> str | None:
        """Acquire a lease lock"""
        try:
            with self._lock:
                lock_key = self.get_key_with_namespace(lock_key)
                if lock_key in self._leases:
                    logger.warning("Lock %s already exists", lock_key)
                    return None

                lock = Lock(lock_key, ttl=ttl, client=self.client)
                success = lock.acquire()

                if success:
                    self._leases[lock_key] = lock.lease
                    logger.info("Acquired lock %s with lease %s",
                                lock_key,
                                lock.lease.uuid if hasattr(lock.lease, 'uuid') else lock.uuid)
                    return str(lock.lease.uuid if hasattr(lock.lease, 'uuid') else lock.uuid)
                else:
                    logger.error("Failed to acquire lock %s", lock_key)
                    return None

        except Exception as e:
            logger.error("Error acquiring lock %s: %s", lock_key, e)
            return None

    def renew_lease(self, lock_key: str) -> bool:
        """Renew lease for a lock"""
        try:
            with self._lock:
                lock_key = self.get_key_with_namespace(lock_key)
                if lock_key not in self._leases:
                    logger.warning("Lock %s does not exist", lock_key)
                    return False

                lease = self._leases[lock_key]
                lease.refresh()
                logger.info("Renewed lease for lock %s", lock_key)
                return True

        except Exception as e:
            logger.error("Error renewing lease for lock %s: %s, will release", lock_key, e)
            self.release_lock(lock_key)
            return False

    def release_lock(self, lock_key: str) -> bool:
        """Release a lease lock"""
        try:
            with self._lock:
                lock_key = self.get_key_with_namespace(lock_key)
                if lock_key not in self._leases:
                    logger.warning("Lock %s does not exist", lock_key)
                    return False

                lease = self._leases[lock_key]
                lease.revoke()
                del self._leases[lock_key]
                logger.info("Released lock %s", lock_key)
                return True

        except Exception as e:
            logger.error("Error releasing lock %s: %s", lock_key, e)
            del self._leases[lock_key]
            return False

    def put_json(
        self,
        key: str,
        data: BaseModel | dict[str, Any],
        lease: Lease | None = None
    ) -> bool:
        """Store JSON data (pydantic compatible)"""
        try:
            if isinstance(data, BaseModel):
                json_data = data.model_dump_json()
            else:
                json_data = json.dumps(data, ensure_ascii=False)

            # etcd3gw expects string, not bytes
            value = json_data

            key = self.get_key_with_namespace(key)
            if lease:
                self.client.put(key, value, lease=lease)
            else:
                self.client.put(key, value)

            logger.debug("Stored JSON data at key %s", key)
            return True

        except Exception as e:
            logger.error("Error storing JSON data at key %s: %s", key, e)
            return False

    def get_json(
        self,
        key: str,
        model_class: Type[T] | None = None
    ) -> dict[str, Any] | T | None:
        """Retrieve JSON data"""
        try:
            key = self.get_key_with_namespace(key)
            value = self.client.get(key)

            if value is None:
                logger.debug("Key %s not found", key)
                return None

            # etcd3gw get() returns decoded string directly
            data = json.loads(value)

            if model_class:
                return model_class(**data)
            else:
                return data

        except Exception as e:
            logger.error("Error retrieving JSON data from key %s: %s", key, e)
            return None

    def put_instances(self, instances: dict[int, Any], prefix: str = "/instances") -> bool:
        """Store instances dictionary"""
        try:
            self.delete_prefix(prefix)

            for instance_id, instance in instances.items():
                key = f"{prefix}/{instance_id}"
                if not self.put_json(key, instance):
                    logger.error("Failed to store instance %d", instance_id)
                    return False

            logger.info("Stored %d instances with prefix %s", len(instances), prefix)
            return True

        except Exception as e:
            logger.error("Error storing instances: %s", e)
            return False

    def get_instances(
        self,
        prefix: str = "/instances",
        model_class: Type[T] | None = None
    ) -> dict[int, dict[str, Any] | T]:
        """Retrieve instances dictionary"""
        instances = {}
        try:
            prefix = self.get_key_with_namespace(prefix)
            for value, metadata in self.client.get_prefix(prefix):
                key = metadata['key']  # etcd3gw returns dict, not object
                instance_id = int(key.split('/')[-1])

                json_str = value  # etcd3gw already decodes
                data = json.loads(json_str)

                if model_class:
                    instances[instance_id] = model_class(**data)
                else:
                    instances[instance_id] = data

            logger.debug("Retrieved %d instances with prefix %s", len(instances), prefix)
            return instances

        except Exception as e:
            logger.error("Error retrieving instances: %s", e)
            return {}

    def delete_prefix(self, prefix: str) -> bool:
        """Delete all keys with given prefix"""
        try:
            prefix = self.get_key_with_namespace(prefix)
            self.client.delete_prefix(prefix)
            logger.debug("Deleted all keys with prefix %s", prefix)
            return True

        except Exception as e:
            logger.error("Error deleting prefix %s: %s", prefix, e)
            return False

    def delete_key(self, key: str) -> bool:
        """Delete a specific key"""
        try:
            key = self.get_key_with_namespace(key)
            self.client.delete(key)
            logger.debug("Deleted key %s", key)
            return True

        except Exception as e:
            logger.error("Error deleting key %s: %s", key, e)
            return False

    @contextmanager
    def lock_context(self, lock_key: str, ttl: int = 30):
        """Context manager for automatic lock acquisition and release"""
        lease_id = None
        try:
            lease_id = self.acquire_lock(lock_key, ttl)
            if lease_id is None:
                raise RuntimeError(f"Failed to acquire lock {lock_key}")
            yield lease_id
        finally:
            if lease_id:
                self.release_lock(lock_key)

    def close(self):
        """Close the etcd client"""
        try:
            with self._lock:
                for lock_key in list(self._leases.keys()):
                    self.release_lock(lock_key)

            # etcd3gw doesn't have close method
            logger.info("EtcdClient closed")

        except Exception as e:
            logger.error("Error closing EtcdClient: %s", e)

    def persist_data(self, key_prefix: str, data: dict[str, Any]) -> bool:
        """Persist data dictionary with key prefix"""
        try:
            with self.lock_context(f"persist_{key_prefix}", ttl=30):
                # Delete old data first
                self.delete_prefix(key_prefix)

                # Store new data
                for data_key, data_value in data.items():
                    full_key = f"{key_prefix}/{data_key}"
                    if not self.put_json(full_key, data_value):
                        logger.error("Failed to persist data for key %s", data_key)
                        return False

                logger.info("Persisted %d items with prefix %s", len(data), key_prefix)
                return True

        except Exception as e:
            logger.error("Error persisting data with prefix %s: %s", key_prefix, e)
            return False

    def restore_data(
        self,
        key_prefix: str,
        model_class: Type[T] | None = None
    ) -> dict[str, dict[str, Any] | T] | None:
        """Restore data dictionary from key prefix"""
        try:
            data = self.get_prefix_data(key_prefix, model_class)
            if data:
                logger.info("Restored %d items with prefix %s", len(data), key_prefix)
            return data

        except Exception as e:
            logger.error("Error restoring data with prefix %s: %s", key_prefix, e)
            return None

    def get_prefix_data(
        self,
        key_prefix: str,
        model_class: Type[T] | None = None
    ) -> dict[str, dict[str, Any] | T]:
        """Get all data under a prefix as dictionary"""
        data = {}
        try:
            key_prefix = self.get_key_with_namespace(key_prefix)
            for value, metadata in self.client.get_prefix(key_prefix):
                key = metadata['key']  # etcd3gw returns dict
                # Extract the relative key after prefix
                relative_key = key[len(key_prefix) + 1:]  # +1 for the '/'

                json_str = value  # etcd3gw already decodes
                item_data = json.loads(json_str)

                if model_class:
                    data[relative_key] = model_class(**item_data)
                else:
                    data[relative_key] = item_data

            return data

        except Exception as e:
            logger.error("Error getting prefix data for %s: %s", key_prefix, e)
            return {}
