#!/usr/bin/env python3
# coding=utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

import datetime
import os
import tempfile
import time
import re
import pytest
from unittest.mock import patch

from motor.engine_server.constants.constants import LOG_BACKUP_PATTERN
from motor.engine_server.utils.logger import CustomRotatingHandler

def test_logger_init():
    from motor.engine_server.utils.logger import run_log
    assert run_log is not None


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as temp_dir_name:
        yield temp_dir_name


@pytest.fixture
def base_filename(temp_dir):
    return os.path.join(temp_dir, "customlog.log")


def create_handler(base_filename, max_bytes=0, backup_count=0, delay=False):
    """
    create CustomRotationHandler instance
    """
    handler = CustomRotatingHandler(
        filename=base_filename,
        maxBytes=max_bytes,
        backupCount=backup_count,
        delay=delay,
    )
    return handler

def test_rotation_filename_format(base_filename):
    """
    test backup file name format
    """
    fixed_time = datetime.datetime(2023, 10, 5, 12, 34, 56)
    with patch("datetime.datetime") as mock_datetime:
        mock_datetime.now.return_value = fixed_time
        handler = create_handler(base_filename)
        rotated_name = handler.rotation_filename("unused")
        base = os.path.splitext(base_filename)[0]
        expected_name = f"{base}-2023-10-05T12-34-56.000.log"
        assert rotated_name == expected_name

def test_do_rollover_creates_backup(base_filename, temp_dir):
    """
    test backup file creation
    """
    handler = create_handler(base_filename, backup_count=2)
    with open(base_filename, "w") as f:
        f.write("test log")
    handler.doRollover()
    backups = [f for f in os.listdir(temp_dir) if f != "customlog.log"]
    assert len(backups) == 1
    # Extract timestamp part from filename and check if it matches the pattern
    # Expected format: customlog-YYYY-MM-DDTHH-MM-SS.fff.log
    backup_name = backups[0]
    # Use search instead of match to find the timestamp anywhere in the string
    match = re.search(LOG_BACKUP_PATTERN, backup_name)
    assert match is not None, f"Timestamp pattern not found in backup filename: {backup_name}"

def test_backup_count_enforcement(base_filename, temp_dir):
    """
    test backup count enforcement
    """
    handler = create_handler(base_filename, backup_count=2)
    old_backups = [
        "customlog-2023-10-05T12-00-00.000.log",
        "customlog-2023-10-05T12-10-00.000.log",
        "customlog-2023-10-05T12-20-00.000.log"
    ]
    for fname in old_backups:
        with open(os.path.join(temp_dir, fname), "w") as f:
            f.write("old log")
    with open(base_filename, "w") as f:
        f.write("new log")
    handler.doRollover()
    remaining = sorted(f for f in os.listdir(temp_dir) if f != "customlog.log")
    assert len(remaining) == 2
    assert "customlog-2023-10-05T12-20-00.000.log" in remaining

def test_no_backup_deletion_when_count_zero(base_filename, temp_dir):
    """
    test backup deletion when backup count is zero
    """
    handler = create_handler(base_filename, backup_count=0)
    with open(base_filename, "w") as f:
        f.write("test log")
    handler.doRollover()
    # sleep to ensure that file creation timestamps are not duplicated
    time.sleep(0.1)
    with open(base_filename, "w") as f:
        f.write("test2 log")
    handler.doRollover()
    # sleep to ensure that file creation timestamps are not duplicated
    time.sleep(0.1)
    with open(base_filename, "w") as f:
        f.write("test3 log")
    handler.doRollover()
    backups = [f for f in os.listdir(temp_dir) if f != "customlog.log"]
    assert len(backups) == 3

def test_multiple_rollovers(base_filename, temp_dir):
    """
    test after multiple rollovers, backup files are deleted in chronological order
    """
    handler = create_handler(base_filename, backup_count=2)
    old_backups = [
        "customlog-2023-10-05T12-00-00.000.log",
        "customlog-2023-10-05T12-10-00.000.log",
        "customlog-2023-10-05T12-20-00.000.log"
    ]
    for fname in old_backups:
        with open(os.path.join(temp_dir, fname), "w") as f:
            f.write("old log")
    for _ in range(4):
        with open(base_filename, "w") as f:
            f.write("new log")
        handler.doRollover()
        time.sleep(0.1)
    backups = [f for f in os.listdir(temp_dir) if f != "customlog.log"]
    assert len(backups) == 2
    assert "customlog-2023-10-05T12-00-00.000.log" not in backups
    assert "customlog-2023-10-05T12-10-00.000.log" not in backups
    assert "customlog-2023-10-05T12-20-00.000.log" not in backups

def test_ignores_invalid_filenames(base_filename, temp_dir):
    """
    test ignoring invalid filenames
    """
    handler = create_handler(base_filename, backup_count=1)
    valid_file = "customlog-2023-10-05T12-00-00.000.log"
    invalid_files = [
        "customlog-invalid.log",
        "otherfile.log",
        "customlog-2023-10-05T12-00-00.000.txt"
    ]
    for fname in [valid_file] + invalid_files:
        with open(os.path.join(temp_dir, fname), "w") as f:
            f.write("new log")
    with open(base_filename, "w") as f:
        f.write("new log")
    handler.doRollover()
    remaining = os.listdir(temp_dir)
    for invalid in invalid_files:
        assert invalid in remaining
    backups = [f for f in os.listdir(temp_dir) if re.match(rf"customlog-{LOG_BACKUP_PATTERN}.log", f)]
    assert len(backups) == 1
