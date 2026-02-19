import os
from bot_state import save_state, load_state

TEST_FILE = os.path.join(os.getcwd(), "bots_state.json")

def test_save_and_load():
    # ensure clean
    try:
        if os.path.exists(TEST_FILE):
            os.remove(TEST_FILE)
    except Exception:
        pass

    st = {"scanner": True, "credit_spread": False}
    save_state(st)
    loaded = load_state()
    assert loaded == st

    # cleanup
    try:
        os.remove(TEST_FILE)
    except Exception:
        pass
