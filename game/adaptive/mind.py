"""RobotMind: the adaptive robot's Sense-Think-Act loop as beliefs, desires
and intentions (BDI).

    Beliefs     estimated user state, task status, whether an alternative
                exists, previous response outcomes, and the learned (uncertain)
                model of how this user reacts to each response
    Desires     help the user complete their tasks, keep the collaboration
                going and avoid unnecessary frustration (the reward weights)
    Intention   the current plan for this failure: which response and why

Per failure episode the block controller calls:

    choose(context)              when the robot is back and has failed
    observe(decision, latency_s, t_from, t_to)
                                 when the participant has decided what to do

``observe`` senses the emotion window, updates the belief (hmm.py), scores
the outcome (reward), updates the user model and records everything.
"""
from dataclasses import dataclass, field

from game.adaptive import observations
from game.adaptive.hmm import BeliefFilter
from game.adaptive.policy import BaselineSchedule, UserModel, make_policy
from game.robot import responses


@dataclass
class Beliefs:
    user_state: BeliefFilter
    model: UserModel
    episode: int = 0                        # failure episodes so far
    previous_state: list = None             # belief before the last update
    last_decision: str = None
    tasks: dict = field(default_factory=dict)       # item_id -> status
    history: list = field(default_factory=list)     # (action, observation, reward)


@dataclass
class Desires:
    progress: dict
    valence: dict
    action_cost: dict
    engagement_weight: float
    affect_weight: float

    def reward(self, action, obs, posterior, states):
        engagement = posterior[states.index("receptive")] - posterior[states.index("disengaging")]
        return (self.progress[obs["decision"]]
                + self.engagement_weight * engagement
                + self.affect_weight * observations.valence(obs["emotion"], self.valence)
                - self.action_cost[action])


@dataclass
class Intention:
    action: str
    feedback_type: str
    phase: str                              # baseline | adaptive
    policy: str
    rationale: str
    scores: dict
    belief: dict
    item_id: str = ""


class RobotMind:
    def __init__(self, cfg, policy="mdp", baseline_row=0, seed=None, reader=None):
        self.cfg = cfg
        self.states = cfg["states"]
        model = UserModel(cfg)
        self.beliefs = Beliefs(BeliefFilter(cfg), model)
        r = cfg["reward"]
        self.desires = Desires(r["progress"], r["valence"], r["action_cost"],
                               r["weights"]["engagement"], r["weights"]["affect"])
        self.schedule = BaselineSchedule(baseline_row)
        self.baseline_episodes = cfg["baseline_episodes"]
        self.policy = make_policy(policy, cfg, model, seed)
        self.seed = seed
        self.reader = reader
        self.intention = None

    # -------------------------------------------------------------- think
    def choose(self, item_id, alternative_available=True, retry_available=True):
        """Pick the response to the failure that just happened."""
        b = self.beliefs
        allowed = [a for a in responses.ACTIONS
                   if (a != "a3" or alternative_available) and (a != "a4" or retry_available)]
        action = None
        if b.episode < self.baseline_episodes:
            action = self.schedule.next(allowed)
            phase, rationale, scores = "baseline", f"schedule row {self.schedule.row_index}", {}
        if action is None:
            phase = "adaptive"
            action, rationale, scores = self.policy.choose(
                b.user_state.belief, b.previous_state, b.last_decision, allowed)
        b.tasks.setdefault(item_id, {"failures": 0, "alternative_available": alternative_available})
        b.tasks[item_id]["failures"] += 1
        self.intention = Intention(action, responses.ACTION_FEEDBACK[action], phase,
                                   self.policy.name, rationale, scores,
                                   b.user_state.as_dict(), item_id)
        return self.intention

    # -------------------------------------------------------- sense + adapt
    def observe(self, decision, latency_s, t_from, t_to, intervals=None):
        """Update everything after the participant's decision. ``intervals``
        overrides reading the emotion window (tests)."""
        if self.intention is None:
            raise RuntimeError("observe() without a preceding choose()")
        b = self.beliefs
        action = self.intention.action
        if intervals is None:
            intervals = self.reader.window(t_from, t_to) if self.reader else []
        obs = observations.observe(intervals, t_from, t_to, decision, latency_s,
                                   self.cfg["pause_bins_s"])
        prior, _, posterior = b.user_state.update(b.model.transition(action), obs)
        reward = self.desires.reward(action, obs, posterior, self.states)
        b.model.update(action, prior, posterior, reward)
        b.previous_state, b.last_decision = prior, decision
        b.tasks[self.intention.item_id]["last_decision"] = decision
        b.history.append((action, obs, reward))
        b.episode += 1
        record = {
            "episode": b.episode, "robot_action": action, "phase": self.intention.phase,
            "policy": self.policy.name, "decision": decision,
            "latency_s": round(latency_s, 3), "pause": obs["pause"],
            "emotion": {k: round(v, 3) for k, v in obs["emotion"].items()},
            "dominant_emotion": obs["dominant_emotion"],
            "belief_prior": b.user_state.as_dict(prior),
            "belief_posterior": b.user_state.as_dict(posterior),
            "most_likely": b.user_state.most_likely(),
            "reward": round(reward, 3),
            "model": b.model.summary(),
        }
        self.intention = None
        return record
