import json, os, time, requests
from datetime import datetime

def get_balance(config: dict) -> float:
    """Query SignalWire balance. config has project_id, auth_token, space_url"""
    url = f"https://{config['space_url']}/api/laml/2010-04-01/Accounts/{config['project_id']}/Balance.json"
    r = requests.get(url, auth=(config['project_id'], config['auth_token']), timeout=10)
    r.raise_for_status()
    return float(r.json().get('balance', 0))

def log_call_cost(call_id: str, balance_before: float, balance_after: float,
                  log_file: str = "logs/campaign_cost.log"):
    cost = balance_before - balance_after
    # Read running total from last line of log
    running_total = 0.0
    if os.path.exists(log_file):
        with open(log_file) as f:
            lines = [l for l in f.readlines() if 'running_total' in l]
            if lines:
                import re
                m = re.search(r'running_total=\$([0-9.]+)', lines[-1])
                if m:
                    running_total = float(m.group(1))
    running_total += cost
    os.makedirs(os.path.dirname(log_file) if os.path.dirname(log_file) else '.', exist_ok=True)
    line = f"[{datetime.now().isoformat()}] call_id={call_id} cost=${cost:.4f} running_total=${running_total:.4f}\n"
    with open(log_file, 'a') as f:
        f.write(line)
    print(f"[COST] {line.strip()}")
    return cost, running_total
