"""Think (state estimation): hidden-Markov belief over the user's state.

    receptive    willing to continue
    frustrated   evidence of dissatisfaction
    disengaging  increasingly unlikely to continue

The belief is updated once per failure episode, after the participant's
decision, with all evidence from that episode:

    b'(s') ∝ P(o | s') * sum_s P(s' | s, a) b(s)

where ``a`` is the response the robot gave and P(s' | s, a) comes from the
robot's learned model of this user (policy.UserModel). The observation
likelihood factorises over the emotion, decision and pause channels; the
emotion channel is soft evidence, so a single short facial reading only
nudges the belief instead of switching the state.
"""
from game.adaptive.observations import INFORMATIVE


def normalise(values):
    total = sum(values)
    if total <= 0:
        return [1.0 / len(values)] * len(values)
    return [v / total for v in values]


class BeliefFilter:
    def __init__(self, cfg):
        self.states = cfg["states"]
        self.emission = cfg["emission"]
        self.belief = normalise(list(cfg["initial_belief"]))

    def likelihood(self, obs):
        """P(observation | state) for every state."""
        out = []
        evidence = obs["emotion"]
        uninformative = evidence.get("uninformative", 1.0)
        for state in self.states:
            table = self.emission["emotion"][state]
            # Uninformative share: same likelihood (mean category probability) in every state.
            emotion = sum(evidence.get(c, 0.0) * table[c] for c in INFORMATIVE)
            emotion += uninformative / len(INFORMATIVE)
            out.append(emotion
                       * self.emission["decision"][state][obs["decision"]]
                       * self.emission["pause"][state][obs["pause"]])
        return out

    @staticmethod
    def predict(belief, transition):
        n = len(belief)
        return [sum(belief[s] * transition[s][t] for s in range(n)) for t in range(n)]

    def update(self, transition, obs):
        """One forward step. Returns (prior, predicted, posterior) beliefs."""
        prior = list(self.belief)
        predicted = self.predict(prior, transition)
        likelihood = self.likelihood(obs)
        self.belief = normalise([p * l for p, l in zip(predicted, likelihood)])
        return prior, predicted, list(self.belief)

    def most_likely(self):
        return self.states[max(range(len(self.belief)), key=self.belief.__getitem__)]

    def as_dict(self, belief=None):
        return {s: round(p, 4) for s, p in zip(self.states, belief or self.belief)}
