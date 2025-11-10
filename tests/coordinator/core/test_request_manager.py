import pytest
import time
import threading
from unittest.mock import patch
from motor.coordinator.core.request_manager import RequestManager


class TestRequestManager:
    """Test cases for RequestManager class"""
    
    def test_singleton_pattern(self):
        """Test that RequestManager follows singleton pattern"""
        # Create two instances
        manager1 = RequestManager()
        manager2 = RequestManager()
        
        # Both should be the same instance
        assert manager1 is manager2
        assert id(manager1) == id(manager2)
    
    def test_generate_request_id_format(self):
        """Test that generated ID has correct format"""
        manager = RequestManager()
        request_id = manager.generate_request_id()
        
        # Should be a string
        assert isinstance(request_id, str)
        # Should be 28 characters (16 timestamp + 4 counter + 8 random)
        assert len(request_id) == 28
        # Should contain only hex characters (0-9, a-f)
        assert all(c in '0123456789abcdef' for c in request_id)
    
    def test_generate_request_id_uniqueness(self):
        """Test that generated IDs are unique"""
        manager = RequestManager()
        
        # Generate multiple IDs
        ids = set()
        for _ in range(1000):
            new_id = manager.generate_request_id()
            # Each ID should be unique
            assert new_id not in ids
            ids.add(new_id)
        
        # Should have 1000 unique IDs
        assert len(ids) == 1000
    
    def test_generate_request_id_thread_safety(self):
        """Test ID generation in multi-threaded environment"""
        manager = RequestManager()
        generated_ids = set()
        lock = threading.Lock()
        
        def generate_ids():
            """Worker function to generate IDs"""
            for _ in range(100):
                new_id = manager.generate_request_id()
                with lock:
                    generated_ids.add(new_id)
        
        # Create and start multiple threads
        threads = []
        for _ in range(10):
            thread = threading.Thread(target=generate_ids)
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Should have 1000 unique IDs (10 threads × 100 IDs each)
        assert len(generated_ids) == 1000
    
    @patch('motor.coordinator.core.request_manager.uuid.uuid4')
    def test_fallback_uuid_generation(self, mock_uuid):
        """Test fallback to UUID when main algorithm fails"""
        manager = RequestManager()
        
        # Mock uuid4 to return a predictable value
        mock_uuid.return_value.hex = 'fallback1234567890abcdef1234567890'
        
        # Force an exception in the main generation logic
        with patch.object(manager, '_lock') as mock_lock:
            mock_lock.__enter__.side_effect = Exception("Test exception")
            
            # Should use fallback UUID
            request_id = manager.generate_request_id()
            assert request_id == 'fallback1234567890abcdef1234567890'
    
    def test_id_structure(self):
        """Test the structural components of generated ID"""
        manager = RequestManager()
        request_id = manager.generate_request_id()
        
        # Extract components
        timestamp_part = request_id[:16]  # First 16 chars: timestamp
        counter_part = request_id[16:20]  # Next 4 chars: counter
        random_part = request_id[20:]     # Last 8 chars: random
        
        # Timestamp should be a valid microsecond timestamp
        assert timestamp_part.isdigit()
        timestamp_val = int(timestamp_part)
        current_micros = int(time.time() * 1000000)
        # Should be within a reasonable range (last 10 seconds)
        assert current_micros - timestamp_val <= 10000000
        
        # Counter should be 4-digit number
        assert counter_part.isdigit()
        assert len(counter_part) == 4
        
        # Random part should be 8 hex characters
        assert len(random_part) == 8
        assert all(c in '0123456789abcdef' for c in random_part)
    
    def test_consecutive_ids_increment_counter(self):
        """Test that counter increments for same timestamp"""
        manager = RequestManager()
        
        # Mock time to return same timestamp
        fixed_time = 1691234567890123
        with patch('motor.coordinator.core.request_manager.time.time') as mock_time:
            mock_time.return_value = fixed_time / 1000000
            
            # Generate multiple IDs with same timestamp
            id1 = manager.generate_request_id()
            id2 = manager.generate_request_id()
            id3 = manager.generate_request_id()
            
            # Extract counters
            counter1 = int(id1[16:20])
            counter2 = int(id2[16:20])
            counter3 = int(id3[16:20])
            
            # Counters should increment
            assert counter2 == counter1 + 1
            assert counter3 == counter2 + 1
            
            # Timestamps should be identical
            assert id1[:16] == id2[:16] == id3[:16]
    
    def test_counter_reset_on_new_timestamp(self):
        """Test that counter resets when timestamp changes"""
        manager = RequestManager()
        
        # First call with timestamp T1
        with patch('motor.coordinator.core.request_manager.time.time') as mock_time:
            mock_time.return_value = 1691234567.890123
            id1 = manager.generate_request_id()
            counter1 = int(id1[16:20])
        
        # Second call with different timestamp T2
        with patch('motor.coordinator.core.request_manager.time.time') as mock_time:
            mock_time.return_value = 1691234567.890124  # Different microsecond
            id2 = manager.generate_request_id()
            counter2 = int(id2[16:20])
        
        # Counter should reset to 0 for new timestamp
        assert counter2 == 0
        # Timestamps should be different
        assert id1[:16] != id2[:16]


@pytest.fixture
def request_manager():
    """Fixture to provide RequestManager instance"""
    return RequestManager()


def test_with_fixture(request_manager):
    """Test using pytest fixture"""
    id1 = request_manager.generate_request_id()
    id2 = request_manager.generate_request_id()
    
    assert isinstance(id1, str)
    assert isinstance(id2, str)
    assert id1 != id2
