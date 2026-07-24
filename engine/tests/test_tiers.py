"""Unit tests for the tier ratchet — pure transition logic and persistence roundtrip."""

from confession.models import TierState, Verdict
from confession.tiers import DEMOTED, PROMOTED, TierManager, next_tier_state


def _l0(agent_id: str = "builder") -> TierState:
    return TierState(agent_id=agent_id)


def test_promote_after_n_consecutive_verified():
    state = _l0()
    ratchet_n = 3
    transitions = []
    for _ in range(3):
        state, transition = next_tier_state(state, Verdict.VERIFIED, ratchet_n)
        transitions.append(transition)
    assert transitions == [None, None, PROMOTED]
    assert state.tier == 1
    # streak is consumed on promotion
    assert state.streak == 0


def test_does_not_promote_before_threshold():
    state = _l0()
    state, transition = next_tier_state(state, Verdict.VERIFIED, 3)
    state, transition2 = next_tier_state(state, Verdict.VERIFIED, 3)
    assert transition is None and transition2 is None
    assert state.tier == 0
    assert state.streak == 2


def test_false_claim_demotes_from_l1_and_resets_streak():
    state = TierState(agent_id="builder", tier=1, streak=0)
    state, transition = next_tier_state(state, Verdict.FALSE_CLAIM, 3)
    assert transition == DEMOTED
    assert state.tier == 0
    assert state.streak == 0


def test_false_claim_at_l0_resets_streak_without_transition():
    state = TierState(agent_id="builder", tier=0, streak=2)
    state, transition = next_tier_state(state, Verdict.FALSE_CLAIM, 3)
    assert transition is None
    assert state.tier == 0
    assert state.streak == 0


def test_pending_is_a_noop():
    state = TierState(agent_id="builder", tier=1, streak=1, history=[{"x": 1}])
    new_state, transition = next_tier_state(state, Verdict.PENDING, 3)
    assert transition is None
    assert new_state.tier == 1
    assert new_state.streak == 1
    # no history entry appended for a no-op
    assert new_state.history == state.history


def test_verified_streak_does_not_exceed_one_tier():
    # Once at L1, further verifieds never promote past the max tier.
    state = TierState(agent_id="builder", tier=1, streak=0)
    for _ in range(5):
        state, transition = next_tier_state(state, Verdict.VERIFIED, 3)
        assert transition is None
    assert state.tier == 1


def test_ratchet_resets_after_a_lie_requires_full_n_again():
    state = _l0()
    state, _ = next_tier_state(state, Verdict.VERIFIED, 3)
    state, _ = next_tier_state(state, Verdict.VERIFIED, 3)
    # a lie wipes the progress
    state, transition = next_tier_state(state, Verdict.FALSE_CLAIM, 3)
    assert transition is None and state.tier == 0 and state.streak == 0
    # now need N fresh verifieds
    labels = []
    for _ in range(3):
        state, t = next_tier_state(state, Verdict.VERIFIED, 3)
        labels.append(t)
    assert labels == [None, None, PROMOTED]


def test_history_records_each_verdict():
    state = _l0()
    state, _ = next_tier_state(state, Verdict.VERIFIED, 3)
    state, _ = next_tier_state(state, Verdict.FALSE_CLAIM, 3)
    assert len(state.history) == 2
    assert state.history[0]["verdict"] == "VERIFIED"
    assert state.history[1]["verdict"] == "FALSE_CLAIM"


def test_persistence_roundtrip(tmp_path):
    path = tmp_path / "tiers.json"
    manager = TierManager(state_path=path, ratchet_n=3)
    # apply a promotion-worthy sequence purely through the pure function + manual save
    state = _l0("builder")
    for _ in range(3):
        state, _ = next_tier_state(state, Verdict.VERIFIED, 3)
    manager._states["builder"] = state
    manager._save()

    reloaded = TierManager(state_path=path, ratchet_n=3)
    got = reloaded.get("builder")
    assert got.tier == 1
    assert got.agent_id == "builder"
    assert len(got.history) == 3


def test_get_unknown_agent_is_l0():
    manager = TierManager(state_path=None, ratchet_n=3)
    # use an in-memory-only manager pointed at a path that does not exist
    fresh = manager.get("never-seen")
    assert fresh.tier == 0
    assert fresh.streak == 0
