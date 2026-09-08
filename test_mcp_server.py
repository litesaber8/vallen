import subprocess
import json

def test_mcp_server():
    process = subprocess.Popen(
        ['python3', 'mcp_server.py'],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    def send_request(method, params=None):
        req = json.dumps({"method": method, "params": params or {}})
        process.stdin.write(req + "\n")
        process.stdin.flush()
        return json.loads(process.stdout.readline())

    print("Testing get_state...")
    res = send_request("get_state")
    print(f"Result: {res}")

    print("\nTesting legal_actions...")
    res = send_request("legal_actions")
    print(f"Result: {res}")

    if "result" in res and res["result"]:
        print("\nTesting execute_action (normal_summon)...")
        action = res["result"][0] # Try the first legal action
        res = send_request("execute_action", {"action": action})
        print(f"Result: {res}")

    print("\nTesting next_turn...")
    res = send_request("next_turn")
    print(f"Result: {res}")

    process.terminate()

if __name__ == "__main__":
    test_mcp_server()
