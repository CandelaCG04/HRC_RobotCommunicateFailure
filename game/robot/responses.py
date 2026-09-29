"""What the robot says, per experimental condition.

The failure *content* (explanation and alternative for each item) lives in
config/items.json. This module only decides which parts are spoken in
which condition, so the manipulation is defined in one place.

Explanations deliberately contain no apology, so that "apology" can later
be tested as its own variant without being confounded with explanation.
"""

# Experimental conditions (how a failure is communicated)
SILENT = "silent"
EXPLANATION = "explanation"
EXPLANATION_ALTERNATIVE = "explanation_alternative"
TUTORIAL = "tutorial"
CONDITIONS = (SILENT, EXPLANATION, EXPLANATION_ALTERNATIVE)

# Feedback types that are not failure conditions
SUCCESS = "success"
SUCCESS_ALTERNATIVE = "success_alternative"
ALTERNATIVE_ACTION = "alternative_action"


def acknowledge(item_name, attempt):
    if attempt == 1:
        return f"Okay, I'll get your {item_name}."
    return "Okay, I'll try again."


def acknowledge_alternative(item_name):
    return f"Okay, I'll get the {item_name}."


def deliver(label, is_alternative=False):
    if is_alternative:
        return f"Here is the {label}."
    return f"Here is your {label}."


def failure_feedback(condition, failure):
    """Return (feedback_type, spoken_text) for a failed attempt."""
    if condition == SILENT:
        return SILENT, ""
    if condition == EXPLANATION_ALTERNATIVE:
        text = f"{failure.explanation} {failure.alternative.offer}"
        return EXPLANATION_ALTERNATIVE, text
    return EXPLANATION, failure.explanation


def offers_alternative(condition):
    return condition == EXPLANATION_ALTERNATIVE
