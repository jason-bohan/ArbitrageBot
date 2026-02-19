import json
import os
from typing import Dict

STATE_FILE = os.path.join(os.getcwd(), "bots_state.json")

def load_state() -> Dict[str, bool]:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception:
        return {}

def save_state(state: Dict[str, bool]) -> None:
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass
