import json
import os
import datetime
import time # For session ID generation if needed, though usually passed in

def generate_session_id() -> str:
    """Generates a unique session ID based on timestamp."""
    return f"sid_{int(time.time() * 1000)}" # Millisecond timestamp based SID

def save_results_to_json(data: dict,
                         base_filename: str,
                         results_dir: str = "results",
                         session_id_override: str = None):
    """
    Saves the given data dictionary to a JSON file in the specified results directory.
    A timestamp and session ID will be part of the filename.

    Args:
        data (dict): The dictionary data to save.
        base_filename (str): The base name for the file (e.g., "tcp_client_results").
        results_dir (str): The main directory where results are stored. Defaults to "results".
        session_id_override (str, optional): Use this SID in filename instead of one from data.

    Returns:
        str: The full path to the saved file, or None if saving failed.
    """
    try:
        if not os.path.exists(results_dir):
            os.makedirs(results_dir, exist_ok=True) # exist_ok=True for concurrent calls
            print(f"Created results directory: {results_dir}")

        # Determine session_id for filename
        sid_for_filename = session_id_override
        if not sid_for_filename:
            # Try to get session_id from common places within the data dict
            if "session_id" in data and isinstance(data["session_id"], (str, int, float)):
                sid_for_filename = str(data["session_id"])
            elif "test_params" in data and isinstance(data["test_params"], dict) and \
                 "session_id" in data["test_params"] and isinstance(data["test_params"]["session_id"], (str, int, float)):
                sid_for_filename = str(data["test_params"]["session_id"])
            elif "client_config" in data and isinstance(data["client_config"], dict) and \
                 "session_id" in data["client_config"] and isinstance(data["client_config"]["session_id"], (str, int, float)):
                sid_for_filename = str(data["client_config"]["session_id"])

        if not sid_for_filename: # If still no SID, generate a generic part or leave it out
            sid_part = "unknownSID"
        else:
            # Sanitize SID for filename (e.g. replace dots from float SIDs)
            sid_part = f"sid_{str(sid_for_filename).replace('.', '_')}"


        timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3] # Milliseconds

        filename = f"{base_filename}_{sid_part}_{timestamp_str}.json"
        filepath = os.path.join(results_dir, filename)

        # Ensure all data is JSON serializable (e.g. convert sets to lists)
        def make_serializable(obj):
            if isinstance(obj, set):
                return list(obj)
            # Add other conversions if necessary, e.g. for datetime objects not handled by default=str
            # if isinstance(obj, datetime.datetime):
            #     return obj.isoformat()
            try: # Check if already serializable
                json.dumps(obj)
                return obj
            except TypeError: # Fallback for other non-serializable types
                return str(obj)


        serializable_data = json.loads(json.dumps(data, default=make_serializable))


        with open(filepath, 'w') as f:
            json.dump(serializable_data, f, indent=4)

        print(f"Results successfully saved to: {filepath}")
        return filepath
    except Exception as e:
        print(f"Error saving results to JSON for {base_filename}: {e} (Data type: {type(data)})")
        # print(f"Problematic data (first few keys): {list(data.keys())[:5]}") # Debugging aid
        return None

if __name__ == '__main__':
    # Example usage
    if not os.path.exists("results"):
        os.makedirs("results")

    client_sid = generate_session_id()
    test_data_client = {
        "test_type": "example_client",
        "session_id": client_sid, # SID from client's perspective
        "value": 100,
        "details": {"info": "some client data", "rtts": [10,12,11], "a_set": {1,2,3}}
    }
    save_results_to_json(test_data_client, "example_client_data", session_id_override=client_sid)

    server_session_sid = client_sid # Server would get this from packet
    test_data_server = {
        "session_id": server_session_sid,
        "client_address": "127.0.0.1:54321",
        "packets_received": 500,
        "events": [{"type": "loss", "count": 2}],
        "received_sn_set": {100, 101, 102} # Example of a set
    }
    # Server might save using its knowledge of the session ID
    save_results_to_json(test_data_server, "example_server_session", session_id_override=server_session_sid)

    generic_data_no_sid = { "info": "data without explicit sid"}
    save_results_to_json(generic_data_no_sid, "generic_data")
