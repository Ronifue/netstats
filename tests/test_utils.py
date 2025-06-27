import unittest
import os
import json
import time
import sys
import shutil # For more robust directory cleanup

# Add src to path to allow direct import of src modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from utils import save_results_to_json, generate_session_id

class TestUtils(unittest.TestCase):
    RESULTS_DIR_TEST = "test_results_temp_utils" # Use a temporary dir for test outputs

    @classmethod
    def setUpClass(cls):
        # Remove dir if it exists from a previous failed run, then create
        if os.path.exists(cls.RESULTS_DIR_TEST):
            shutil.rmtree(cls.RESULTS_DIR_TEST)
        os.makedirs(cls.RESULTS_DIR_TEST, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        # Clean up the temporary results directory and its contents
        if os.path.exists(cls.RESULTS_DIR_TEST):
            shutil.rmtree(cls.RESULTS_DIR_TEST)

    def test_generate_session_id(self):
        sid1 = generate_session_id()
        self.assertIsInstance(sid1, str)
        self.assertTrue(sid1.startswith("sid_"))
        # Check if the part after "sid_" is a number (timestamp based)
        self.assertTrue(sid1.split('_')[1].isdigit())

        time.sleep(0.002) # Ensure timestamp changes for next SID, 2ms should be enough
        sid2 = generate_session_id()
        self.assertNotEqual(sid1, sid2)

    def test_save_results_to_json_with_override_sid(self):
        test_data = {"param1": 10, "param2": "value", "nested": {"a": 1.23}}
        base_filename = "test_output_override"

        session_id_override = "override_sid_123"
        filepath = save_results_to_json(
            test_data,
            base_filename,
            results_dir=self.RESULTS_DIR_TEST,
            session_id_override=session_id_override
        )

        self.assertIsNotNone(filepath)
        self.assertTrue(os.path.exists(filepath))
        # utils.save_results_to_json adds "sid_" prefix internally to the sid_part
        self.assertTrue(f"_sid_{session_id_override}_" in os.path.basename(filepath))
        self.assertTrue(base_filename in os.path.basename(filepath))

        with open(filepath, 'r') as f:
            loaded_data = json.load(f)
        self.assertEqual(test_data, loaded_data)

    def test_save_results_with_session_id_in_data(self):
        session_id_in_data = "data_sid_789"
        test_data_with_sid = {"session_id": session_id_in_data, "value": "test"}
        base_filename = "output_with_sid_in_data"

        filepath = save_results_to_json(test_data_with_sid, base_filename, results_dir=self.RESULTS_DIR_TEST)
        self.assertIsNotNone(filepath)
        self.assertTrue(os.path.exists(filepath))
        self.assertTrue(f"_sid_{session_id_in_data}_" in os.path.basename(filepath))

        with open(filepath, 'r') as f:
            loaded_data = json.load(f)
        self.assertEqual(test_data_with_sid, loaded_data)

    def test_save_results_no_sid_provided_or_in_data(self):
        test_data_no_sid = {"info": "generic data, no session id here"}
        base_filename = "output_no_sid"

        filepath = save_results_to_json(test_data_no_sid, base_filename, results_dir=self.RESULTS_DIR_TEST)
        self.assertIsNotNone(filepath)
        self.assertTrue(os.path.exists(filepath))
        # Expects "_sid_unknownSID_" or similar if no SID found
        self.assertTrue("_sid_unknownSID_" in os.path.basename(filepath))

        with open(filepath, 'r') as f:
            loaded_data = json.load(f)
        self.assertEqual(test_data_no_sid, loaded_data)


    def test_save_results_with_set_in_data(self):
        test_data_with_set = {"my_set": {1, 2, 3, "apple"}, "value": "set_test"}
        base_filename = "output_with_set"
        sid_for_file = "set_test_sid"
        filepath = save_results_to_json(test_data_with_set, base_filename, results_dir=self.RESULTS_DIR_TEST, session_id_override=sid_for_file)

        self.assertIsNotNone(filepath)
        self.assertTrue(os.path.exists(filepath))

        with open(filepath, 'r') as f:
            loaded_data = json.load(f)

        self.assertIsInstance(loaded_data["my_set"], list)
        # Use assertCountEqual for lists where order doesn't matter, esp. after set to list conversion
        self.assertCountEqual(loaded_data["my_set"], [1, 2, 3, "apple"])
        self.assertEqual(loaded_data["value"], "set_test")

if __name__ == '__main__':
    unittest.main()
```
