"""Think (decision): which failure response to give next.

    BaselineSchedule  the first failures: every action once, counterbalanced
    HeuristicPolicy   ordered if-then rules on the belief (simplest baseline)
    MDPPolicy         small MDP over (state, action), solved by value iteration
                      on a Thompson sample of the learned UserModel and applied
                      to the belief with QMDP: argmax_a sum_s b(s) Q(s, a)
    UserModel         what the robot learns about this user: how each response
                      changes their state (Dirichlet counts) and how rewarding
                      it is in each state (Gaussian mean with uncertainty)
"""
import math
import random

from game.robot.responses import ACTIONS


# ------------------------------------------------------------- baseline
def williams_design(items):
    """Counterbalanced orders in which every item appears once per row in
    every position equally often and, for an odd count, every item follows
    every other equally often (Williams design: 2n rows for odd n)."""
    n = len(items)
    first, low, high = [0], 1, n - 1
    while len(first) < n:
        first.append(low)
        low += 1
        if len(first) < n:
            first.append(high)
            high -= 1
    rows = [[(x + i) % n for x in first] for i in range(n)]
    if n % 2:
        rows += [list(reversed(r)) for r in rows]
    return [[items[x] for x in row] for row in rows]


BASELINE_ROWS = williams_design(ACTIONS)


class BaselineSchedule:
    def __init__(self, row_index):
        self.row_index = row_index % len(BASELINE_ROWS)
        self.order = list(BASELINE_ROWS[self.row_index])
        self.remaining = list(self.order)

    def next(self, allowed):
        """Next scheduled action that is allowed now (a not-yet-allowed one,
        e.g. a4 when no retry is left, moves back in the queue)."""
        for i, action in enumerate(self.remaining):
            if action in allowed:
                return self.remaining.pop(i)
        return None

    @property
    def done(self):
        return not self.remaining


# ------------------------------------------------------------ user model
class UserModel:
    def __init__(self, cfg):
        self.states = cfg["states"]
        n = len(self.states)
        strength = cfg["prior_strength"]
        prior = cfg["transition_prior"]
        self.alpha = {}
        for action in ACTIONS:
            rows = {**prior["default"], **prior.get(action, {})}
            self.alpha[action] = [[strength * p for p in rows[s]] for s in self.states]
        rp = cfg["reward_prior"]
        self.reward_mean = [[rp[s][a] for a in ACTIONS] for s in self.states]
        self.reward_count = [[cfg["reward_prior_count"]] * len(ACTIONS) for _ in range(n)]
        self.noise_sd = cfg["reward_noise_sd"]

    def transition(self, action):
        """Posterior-mean P(s' | s, action)."""
        return [[a / sum(row) for a in row] for row in self.alpha[action]]

    def update(self, action, prior, posterior, reward):
        """Soft counts: the state before (prior belief) and after (posterior)
        are uncertain, so each (s, s') pair gets weight b(s) b'(s')."""
        j = ACTIONS.index(action)
        for s, ps in enumerate(prior):
            for t, pt in enumerate(posterior):
                self.alpha[action][s][t] += ps * pt
            if ps > 0:
                n = self.reward_count[s][j] + ps
                self.reward_mean[s][j] += ps * (reward - self.reward_mean[s][j]) / n
                self.reward_count[s][j] = n

    def sample(self, rng):
        """One Thompson sample: transitions ~ Dirichlet, rewards ~ Normal."""
        transitions = {}
        for action in ACTIONS:
            rows = []
            for row in self.alpha[action]:
                draw = [rng.gammavariate(a, 1.0) for a in row]
                rows.append([d / sum(draw) for d in draw])
            transitions[action] = rows
        rewards = [[rng.gauss(m, self.noise_sd / math.sqrt(c)) for m, c in zip(ms, cs)]
                   for ms, cs in zip(self.reward_mean, self.reward_count)]
        return transitions, rewards

    def mean(self):
        return {a: self.transition(a) for a in ACTIONS}, [list(r) for r in self.reward_mean]

    def summary(self):
        """Compact record of what has been learned (for the log)."""
        return {
            "reward_mean": {s: {a: round(self.reward_mean[i][j], 3) for j, a in enumerate(ACTIONS)}
                            for i, s in enumerate(self.states)},
            "reward_n": {s: {a: round(self.reward_count[i][j], 2) for j, a in enumerate(ACTIONS)}
                         for i, s in enumerate(self.states)},
        }


def value_iteration(transitions, rewards, discount, iterations=100):
    """Q(s, a) for the small MDP (all actions assumed available later)."""
    n = len(rewards)
    values = [0.0] * n
    q = [[0.0] * len(ACTIONS) for _ in range(n)]
    for _ in range(iterations):
        q = [[rewards[s][j] + discount * sum(transitions[a][s][t] * values[t] for t in range(n))
              for j, a in enumerate(ACTIONS)] for s in range(n)]
        values = [max(row) for row in q]
    return q


# -------------------------------------------------------------- policies
class HeuristicPolicy:
    name = "heuristic"

    def __init__(self, cfg):
        self.rules = cfg["heuristic_rules"]
        self.states = cfg["states"]

    def choose(self, belief, previous_belief, last_decision, allowed):
        frustrated = self.states.index("frustrated")
        most_likely = self.states[max(range(len(belief)), key=belief.__getitem__)]
        rising = (belief[frustrated] - previous_belief[frustrated]) if previous_belief else 0.0
        for rule in self.rules:
            when = rule["when"]
            hit = (
                (when == "frustration_rising" and rising > rule["threshold"])
                or (when == "most_likely" and most_likely == rule["state"])
                or (when == "last_decision" and last_decision == rule["decision"])
                or when == "always"
            )
            if hit and rule["action"] in allowed:
                return rule["action"], f"rule {when}" + (
                    f"={rule.get('state') or rule.get('decision')}"
                    if when in ("most_likely", "last_decision") else ""), {}
        action = sorted(allowed)[0]
        return action, "no rule matched", {}


class MDPPolicy:
    name = "mdp"

    def __init__(self, cfg, model, rng):
        self.model = model
        self.rng = rng
        self.discount = cfg["discount"]

    def choose(self, belief, previous_belief, last_decision, allowed):
        transitions, rewards = self.model.sample(self.rng)
        q = value_iteration(transitions, rewards, self.discount)
        scores = {a: sum(b * q[s][j] for s, b in enumerate(belief))
                  for j, a in enumerate(ACTIONS)}
        action = max((a for a in ACTIONS if a in allowed), key=scores.get)
        return action, "QMDP on a Thompson sample", {a: round(v, 3) for a, v in scores.items()}


def make_policy(name, cfg, model, seed=None):
    if name == "heuristic":
        return HeuristicPolicy(cfg)
    if name == "mdp":
        return MDPPolicy(cfg, model, random.Random(seed))
    raise ValueError(f"unknown policy '{name}' (heuristic or mdp)")
