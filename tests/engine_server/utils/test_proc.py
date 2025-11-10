#!/usr/bin/env python3
# coding=utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

import signal
import pytest
from unittest import mock
from multiprocessing.process import BaseProcess

from motor.engine_server.utils import proc


class TestProcUtils:

    @mock.patch('psutil.Process')
    def test_get_child_processes(self, mock_psutil_process):
        # Mock base processes
        mock_base_proc1 = mock.Mock(spec=BaseProcess)
        mock_base_proc1.is_alive.return_value = True
        mock_base_proc1.pid = 100

        mock_base_proc2 = mock.Mock(spec=BaseProcess)
        mock_base_proc2.is_alive.return_value = False
        mock_base_proc2.pid = 200

        # Mock psutil process and children
        mock_psutil_instance = mock_psutil_process.return_value
        mock_child1 = mock.Mock()
        mock_child1.pid = 101
        mock_child2 = mock.Mock()
        mock_child2.pid = 102
        mock_psutil_instance.children.return_value = [mock_child1, mock_child2]

        # Test with recursive=False
        result = proc.get_child_processes([mock_base_proc1, mock_base_proc2], recursive=False)

        # Verify results
        assert len(result) == 2
        assert result[0] == mock_child1
        assert result[1] == mock_child2
        mock_psutil_instance.children.assert_called_once_with(recursive=False)

        # Reset mocks
        mock_psutil_process.reset_mock()
        mock_psutil_instance.reset_mock()

        # Test with recursive=True
        result = proc.get_child_processes([mock_base_proc1], recursive=True)
        mock_psutil_instance.children.assert_called_once_with(recursive=True)

    @mock.patch('psutil.Process')
    def test_get_child_processes_exceptions(self, mock_psutil_process):
        # Mock base process
        mock_base_proc = mock.Mock(spec=BaseProcess)
        mock_base_proc.is_alive.return_value = True
        mock_base_proc.pid = 100

        # Test NoSuchProcess exception
        mock_psutil_process.side_effect = MockPsutilExceptions.NoSuchProcess
        result = proc.get_child_processes([mock_base_proc])
        assert len(result) == 0

        # Test AccessDenied exception
        mock_psutil_process.side_effect = MockPsutilExceptions.AccessDenied
        result = proc.get_child_processes([mock_base_proc])
        assert len(result) == 0


    @mock.patch('contextlib.suppress')
    @mock.patch('os.kill')
    @mock.patch('psutil.Process')
    def test_kill_process_tree(self, mock_psutil_process, mock_os_kill, mock_suppress):
        # Mock psutil process and children
        mock_parent = mock_psutil_process.return_value
        mock_child1 = mock.Mock()
        mock_child1.pid = 101
        mock_child2 = mock.Mock()
        mock_child2.pid = 102
        mock_parent.children.return_value = [mock_child1, mock_child2]

        # Test kill_process_tree
        proc.kill_process_tree(100)

        # Verify children killed first
        assert mock_os_kill.call_count == 3  # 2 children + 1 parent
        # Check the pids and that signals are provided
        pids_called = [call[0][0] for call in mock_os_kill.call_args_list]
        assert 101 in pids_called
        assert 102 in pids_called
        assert 100 in pids_called

        # Verify contextlib.suppress called with ProcessLookupError
        assert mock_suppress.call_count == 3
        for call in mock_suppress.call_args_list:
            assert call[0][0] == ProcessLookupError

    @mock.patch('psutil.Process')
    def test_kill_process_tree_no_such_process(self, mock_psutil_process):
        # Mock NoSuchProcess exception
        mock_psutil_process.side_effect = MockPsutilExceptions.NoSuchProcess

        # Test with non-existent process
        proc.kill_process_tree(999)

        # Verify no further calls
        mock_psutil_process.assert_called_once_with(999)


# Add psutil exceptions to namespace for proper mocking
class MockPsutilExceptions:
    class NoSuchProcess(Exception):
        pass

    class AccessDenied(Exception):
        pass


# Patch psutil with our mock exceptions during tests
@pytest.fixture(autouse=True)
def patch_dependencies(monkeypatch):
    # Mock psutil exceptions
    monkeypatch.setattr('psutil.NoSuchProcess', MockPsutilExceptions.NoSuchProcess)
    monkeypatch.setattr('psutil.AccessDenied', MockPsutilExceptions.AccessDenied)
    # Mock SIGKILL for Windows compatibility
    monkeypatch.setattr('signal.SIGKILL', signal.SIGTERM)  # Use SIGTERM instead
    yield
