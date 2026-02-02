import unittest

from silvasonic.controller.hardware import AudioDevice
from silvasonic.controller.profiles import ProfileManager, RecorderProfile


class TestProfileManager(unittest.TestCase):
    """Test suite for the ProfileManager class."""

    def setUp(self):
        """Set up test fixtures."""
        # Create a temporary directory structure for profiles would be ideal
        # But for unit tests, we can mock the loader or the file system.
        pass

    def test_load_profiles(self):
        """Test that profiles are correctly matched to audio devices."""
        # Mocking file operations is tedious, let's test the matching logic primarily
        # by manually populating self.profiles
        manager = ProfileManager()
        # Clear any failed loads
        manager.profiles = []

        # Add mock profiles
        p1 = RecorderProfile(
            slug="ultramic", name="Ultramic", match_pattern="ultramic|dodotronic", raw_config={}
        )
        p2 = RecorderProfile(slug="laptop", name="Laptop", match_pattern="HDA Intel", raw_config={})
        manager.profiles = [p1, p2]

        # Test Case 1: Match Ultramic
        dev1 = AudioDevice(
            card_index=0,
            id="Ultramic384E",
            description="UltraMic384K_EVO 16bit r0",
            serial_number="123",
        )
        self.assertEqual(manager.find_profile_for_device(dev1), "ultramic")

        # Test Case 2: Match Dodotronic (via description)
        dev2 = AudioDevice(
            card_index=1, id="GenericUSB", description="Dodotronic UltraMic", serial_number="456"
        )
        self.assertEqual(manager.find_profile_for_device(dev2), "ultramic")

        # Test Case 3: Match Laptop
        dev3 = AudioDevice(
            card_index=2, id="HDA Intel", description="Realtek ALC", serial_number="789"
        )
        self.assertEqual(manager.find_profile_for_device(dev3), "laptop")

        # Test Case 4: No Match
        dev4 = AudioDevice(
            card_index=3, id="RandomUSB", description="Some Mic", serial_number="000"
        )
        self.assertIsNone(manager.find_profile_for_device(dev4))


if __name__ == "__main__":
    unittest.main()
