"""Builds a participant's session plan from the JSON config files.

config/items.json         every item: where it is and how it can fail
config/blocks.json        which items appear in each block, success/fail
config/counterbalance.json  condition orders (one per participant number)
"""
import json
import random
import re
from dataclasses import dataclass
from typing import Optional

from game import settings
from game.robot import responses


@dataclass(frozen=True)
class Alternative:
    offer: str                      # sentence appended to the explanation
    button: str                     # label of the "accept" button
    item_name: str = ""             # what the robot fetches instead
    fetch_spot: Optional[str] = None    # None = no trip, just ``reply``
    reply: str = ""                 # spoken when accepted without a trip
    use: str = ""                   # activity the alternative unlocks
    do: Optional[dict] = None       # hands-on interaction for that activity


@dataclass(frozen=True)
class Failure:
    type: str                       # perception / manipulation / navigation
    stop_spot: str                  # where the robot goes before failing
    explanation: str
    alternative: Alternative


@dataclass(frozen=True)
class TrialItem:
    item_id: str
    name: str
    spot: str
    use: str                        # activity the item unlocks
    do: dict                        # hands-on interaction (interactions.py)
    succeeds: bool
    failure: Optional[Failure]


@dataclass
class BlockPlan:
    index: int
    block_id: str
    condition: str
    title: str
    goal: str
    items: list

    @property
    def is_tutorial(self):
        return self.block_id == "tutorial"


def _load(name):
    with open(settings.CONFIG_DIR / name, encoding="utf-8") as handle:
        return json.load(handle)


def participant_number(pid):
    """'P07' -> 7. Returns 0 if the id contains no digits."""
    digits = re.findall(r"\d+", pid)
    return int(digits[-1]) if digits else 0


INTERACTION_TYPES = ("hold", "tap", "drag", "sequence", "slider")


def _parse_do(owner, spec, name):
    """Check an interaction spec; default is clicking the item 3 times."""
    if spec is None:
        return {"type": "tap", "count": 3,
                "prompt": f"Click the {name} to use it"}
    if spec.get("type") not in INTERACTION_TYPES:
        raise ValueError(f"'{owner}': interaction type must be one of "
                         f"{INTERACTION_TYPES}")
    if spec["type"] == "sequence" and not spec.get("sequence"):
        raise ValueError(f"'{owner}': a sequence needs a 'sequence' list")
    return spec


def _parse_item(item_id, entry, outcome):
    if outcome not in ("success", "fail"):
        raise ValueError(f"Outcome for '{item_id}' must be success or fail")
    failure = None
    if outcome == "fail":
        spec = entry.get("failure")
        if spec is None:
            raise ValueError(f"Item '{item_id}' is set to fail but has no "
                             f"'failure' entry in items.json")
        alt = dict(spec["alternative"])
        alt["do"] = _parse_do(f"{item_id} alternative", alt.get("do"),
                              alt.get("item_name") or entry["name"])
        failure = Failure(
            type=spec["type"],
            stop_spot=spec.get("stop_spot", entry["spot"]),
            explanation=spec["explanation"],
            alternative=Alternative(**alt),
        )
        if not failure.alternative.use:
            raise ValueError(f"Alternative for '{item_id}' needs a 'use'")
    use = entry.get("use") or f"Use the {entry['name']}"
    do = _parse_do(item_id, entry.get("do"), entry["name"])
    return TrialItem(item_id, entry["name"], entry["spot"], use, do,
                     outcome == "success", failure)


def build_session(pid, order_index=None, include_tutorial=True,
                  assignment="random"):
    """Return (list of BlockPlan, order_index, condition order).

    The condition order is one of the permutations in counterbalance.json:
      - ``order_index`` given: use exactly that order (e.g. to redo a run)
      - assignment "random": pick one at random for this session (default)
      - assignment "balanced": rotate by participant number, so P01..P06
        together cover every order once
    """
    items = _load("items.json")
    blocks = _load("blocks.json")
    balance = _load("counterbalance.json")

    orders = balance["orders"]
    if order_index is None:
        if assignment == "balanced":
            order_index = (participant_number(pid) - 1) % len(orders)
        elif assignment == "random":
            order_index = random.SystemRandom().randrange(len(orders))
        else:
            raise ValueError(f"Unknown assignment '{assignment}'")
    order = orders[order_index]
    for condition in order:
        if condition not in responses.CONDITIONS:
            raise ValueError(f"Unknown condition '{condition}'")

    sequence = [("tutorial", responses.TUTORIAL)] if include_tutorial else []
    sequence += list(zip(balance["block_order"], order))

    plans = []
    for index, (block_id, condition) in enumerate(sequence):
        spec = blocks[block_id]
        trial_items = []
        for trial in spec["items"]:
            if trial["item"] not in items:
                raise KeyError(f"Block '{block_id}' uses unknown item "
                               f"'{trial['item']}'")
            trial_items.append(_parse_item(
                trial["item"], items[trial["item"]], trial["outcome"]))
        plans.append(BlockPlan(index, block_id, condition, spec["title"],
                               spec["goal"], trial_items))
    return plans, order_index, order