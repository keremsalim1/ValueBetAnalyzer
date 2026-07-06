"""Disabled markets persistence"""
import json,os,logging

logger = logging.getLogger(__name__)

STORE_PATH=os.path.join(os.path.dirname(__file__),"disabled_markets.json")

def load_disabled_markets()->set:
    try:
        with open(STORE_PATH,"r") as f:
            return set(json.load(f))
    except FileNotFoundError:
        return set()
    except Exception:
        logger.warning("disabled_markets load failed",exc_info=True)
        return set()

def save_disabled_markets(markets):
    with open(STORE_PATH,"w") as f:
        json.dump(list(markets),f)
