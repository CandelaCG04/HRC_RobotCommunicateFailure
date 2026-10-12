"""Sense: one failure episode -> observation for the state estimate.

Three channels, all taken from the window between the failure message and
the participant's decision:

    emotion   soft evidence: share of the window spent in each stable emotion,
              weighted by the classifier's confidence
    decision  retry, accept_alt, self, switch ("something else", the closest
              to rephrasing a request) or give_up (abandoning the item)
    pause     decision latency, binned fast / normal / slow ("waits")
"""
# FEmotion label -> evidence category. Fear and surprise are ambiguous: they
# are kept apart from the informative categories and carry no evidence.
CATEGORY = {
    "happy": "happy", "angry": "anger", "sad": "sadness", "disgust": "disgust",
    "neutral": "neutral", "fear": "ambiguous", "surprise": "ambiguous",
}
INFORMATIVE = ("happy", "anger", "sadness", "disgust", "neutral")
DECISIONS = ("retry", "accept_alt", "self", "switch", "give_up")
PAUSES = ("fast", "normal", "slow")


def emotion_evidence(intervals, t_from, t_to):
    """Fractions of the window per informative category, plus 'uninformative'
    (ambiguous emotions, the unsure part of each reading, and no face).
    The values sum to 1."""
    span = max(t_to - t_from, 1e-9)
    weight = dict.fromkeys(INFORMATIVE, 0.0)
    uninformative = 0.0
    covered = 0.0
    for emotion, start, end, confidence in intervals:
        dwell = max(0.0, min(end, t_to) - max(start, t_from))
        if dwell <= 0:
            continue
        covered += dwell
        category = CATEGORY.get(emotion, "ambiguous")
        conf = 1.0 if confidence is None else min(1.0, max(0.0, confidence))
        if category in weight:
            weight[category] += dwell * conf
            uninformative += dwell * (1.0 - conf)
        else:
            uninformative += dwell
    uninformative += max(0.0, span - covered)          # no face visible
    total = sum(weight.values()) + uninformative
    evidence = {k: v / total for k, v in weight.items()}
    evidence["uninformative"] = uninformative / total
    evidence["face_seconds"] = covered
    return evidence


def dominant_emotion(evidence):
    """Informative category with the largest share, or None if none observed."""
    best = max(INFORMATIVE, key=lambda k: evidence.get(k, 0.0))
    return best if evidence.get(best, 0.0) > 0 else None


def valence(evidence, values):
    """Weighted emotional valence of the window (config reward.valence)."""
    return sum(evidence.get(k, 0.0) * values.get(k, 0.0) for k in INFORMATIVE)


def pause_bin(latency_s, bins):
    if latency_s < bins["fast_below"]:
        return "fast"
    if latency_s >= bins["slow_from"]:
        return "slow"
    return "normal"


def observe(intervals, t_from, t_to, decision, latency_s, bins):
    if decision not in DECISIONS:
        raise ValueError(f"unknown decision '{decision}'")
    evidence = emotion_evidence(intervals, t_from, t_to)
    return {
        "emotion": evidence,
        "dominant_emotion": dominant_emotion(evidence),
        "decision": decision,
        "latency_s": latency_s,
        "pause": pause_bin(latency_s, bins),
    }
