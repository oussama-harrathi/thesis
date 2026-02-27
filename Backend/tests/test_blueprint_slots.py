"""
Unit tests for blueprint slot allocation logic.

Covers:
  - _distribute()               — integer distribution with largest-remainder
  - BlueprintService.expand_to_slots()  — auto mode and manual mode

No database or LLM calls are made.
"""
import uuid

import pytest

from app.schemas.blueprint import (
    BlueprintConfig,
    DifficultyMix,
    QuestionTypeCounts,
    TopicEntry,
    TopicMix,
)
from app.services.blueprint_service import (
    BlueprintService,
    GenerationSlot,
    _distribute,
)


# ── _distribute ───────────────────────────────────────────────────────────────

class TestDistribute:
    def test_output_sums_to_total(self):
        result = _distribute(10, {"a": 1, "b": 1, "c": 1})
        assert sum(result.values()) == 10

    def test_exact_equal_split(self):
        result = _distribute(9, {"a": 1, "b": 1, "c": 1})
        assert sum(result.values()) == 9
        assert all(v == 3 for v in result.values())

    def test_remainder_distributed_to_largest_fraction(self):
        # 10 total, 3 equal weights → 4+3+3=10 (one key gets the extra 1)
        result = _distribute(10, {"a": 1, "b": 1, "c": 1})
        assert sum(result.values()) == 10
        assert max(result.values()) - min(result.values()) <= 1

    def test_zero_total_returns_all_zeros(self):
        result = _distribute(0, {"a": 0.5, "b": 0.5})
        assert result == {"a": 0, "b": 0}

    def test_zero_total_weight_returns_zeros(self):
        result = _distribute(10, {"a": 0.0, "b": 0.0})
        assert sum(result.values()) == 0

    def test_single_key_gets_all(self):
        result = _distribute(7, {"only": 1.0})
        assert result == {"only": 7}

    def test_proportional_allocation(self):
        result = _distribute(10, {"easy": 0.5, "hard": 0.5})
        assert sum(result.values()) == 10
        assert abs(result["easy"] - result["hard"]) <= 1

    def test_unequal_weights_favour_larger(self):
        result = _distribute(10, {"big": 3.0, "small": 1.0})
        assert sum(result.values()) == 10
        assert result["big"] > result["small"]

    def test_large_total(self):
        result = _distribute(100, {"a": 1, "b": 2, "c": 3})
        assert sum(result.values()) == 100

    def test_keys_preserved(self):
        result = _distribute(5, {"alpha": 1, "beta": 1})
        assert set(result.keys()) == {"alpha", "beta"}


# ── BlueprintService.expand_to_slots (auto mode) ─────────────────────────────

def _auto_config(mcq: int = 0, tf: int = 0, sa: int = 0, essay: int = 0) -> BlueprintConfig:
    """Helper: build a BlueprintConfig in auto mode with specified counts."""
    # Ensure at least one type > 0
    if mcq + tf + sa + essay == 0:
        raise ValueError("Need at least one question")
    return BlueprintConfig(
        question_counts=QuestionTypeCounts(
            mcq=mcq,
            true_false=tf,
            short_answer=sa,
            essay=essay,
        ),
        difficulty_mix=DifficultyMix(easy=0.34, medium=0.33, hard=0.33),
        topic_mix=TopicMix(mode="auto"),
    )


class TestExpandToSlotsAuto:
    def test_total_slot_count_equals_config_total(self):
        config = _auto_config(mcq=6, tf=4, sa=2, essay=2)
        slots = BlueprintService.expand_to_slots(config)
        total_generated = sum(s.count for s in slots)
        assert total_generated == config.question_counts.total

    def test_all_slots_have_topic_id_none(self):
        config = _auto_config(mcq=5, sa=5)
        slots = BlueprintService.expand_to_slots(config)
        assert all(s.topic_id is None for s in slots)

    def test_only_nonzero_types_appear(self):
        config = _auto_config(mcq=4, tf=0, sa=0, essay=0)
        slots = BlueprintService.expand_to_slots(config)
        from app.models.question import QuestionType
        assert all(s.question_type == QuestionType.mcq for s in slots)

    def test_zero_difficulty_proportion_not_in_slots(self):
        config = BlueprintConfig(
            question_counts=QuestionTypeCounts(mcq=10),
            difficulty_mix=DifficultyMix(easy=0.5, medium=0.5, hard=0.0),
            topic_mix=TopicMix(mode="auto"),
        )
        slots = BlueprintService.expand_to_slots(config)
        from app.models.question import Difficulty
        hard_slots = [s for s in slots if s.difficulty == Difficulty.hard]
        assert hard_slots == []

    def test_single_mcq_slot_returns_nonempty(self):
        config = _auto_config(mcq=3)
        slots = BlueprintService.expand_to_slots(config)
        assert len(slots) >= 1

    def test_returned_type_is_list_of_generation_slots(self):
        config = _auto_config(mcq=4, tf=2)
        slots = BlueprintService.expand_to_slots(config)
        assert isinstance(slots, list)
        assert all(isinstance(s, GenerationSlot) for s in slots)

    def test_all_difficulties_present_when_mix_nonzero(self):
        config = _auto_config(mcq=9)  # 9 evenly over 3 difficulties → 3+3+3
        slots = BlueprintService.expand_to_slots(config)
        from app.models.question import Difficulty
        difficulties_seen = {s.difficulty for s in slots}
        assert Difficulty.easy in difficulties_seen
        assert Difficulty.medium in difficulties_seen
        assert Difficulty.hard in difficulties_seen

    def test_total_count_preserved_for_mixed_types(self):
        config = _auto_config(mcq=5, tf=3, sa=2, essay=2)
        slots = BlueprintService.expand_to_slots(config)
        assert sum(s.count for s in slots) == 12


# ── BlueprintService.expand_to_slots (manual mode) ───────────────────────────

def _manual_config(
    mcq: int,
    sa: int,
    topics: list[tuple[uuid.UUID, int]],
) -> BlueprintConfig:
    """Helper: build a manual-mode config."""
    return BlueprintConfig(
        question_counts=QuestionTypeCounts(mcq=mcq, short_answer=sa),
        difficulty_mix=DifficultyMix(easy=0.5, medium=0.5, hard=0.0),
        topic_mix=TopicMix(
            mode="manual",
            topics=[TopicEntry(topic_id=tid, question_count=cnt) for tid, cnt in topics],
        ),
    )


class TestExpandToSlotsManual:
    def test_total_count_matches_topic_sum(self):
        t1 = uuid.uuid4()
        t2 = uuid.uuid4()
        config = _manual_config(mcq=6, sa=4, topics=[(t1, 5), (t2, 5)])
        slots = BlueprintService.expand_to_slots(config)
        assert sum(s.count for s in slots) == 10

    def test_slots_carry_topic_ids(self):
        t1 = uuid.uuid4()
        config = _manual_config(mcq=4, sa=0, topics=[(t1, 4)])
        # Need at least one non-zero type; sa=0 is filtered
        slots = BlueprintService.expand_to_slots(config)
        topic_ids = {s.topic_id for s in slots}
        assert t1 in topic_ids

    def test_two_topics_both_present(self):
        t1, t2 = uuid.uuid4(), uuid.uuid4()
        config = _manual_config(mcq=4, sa=4, topics=[(t1, 4), (t2, 4)])
        slots = BlueprintService.expand_to_slots(config)
        topic_ids = {s.topic_id for s in slots}
        assert t1 in topic_ids
        assert t2 in topic_ids

    def test_topic_with_zero_allocation_not_in_slots(self):
        t1, t2 = uuid.uuid4(), uuid.uuid4()
        # Only mcq requested; t2 gets 0 questions after rounding with 1-question total
        config = BlueprintConfig(
            question_counts=QuestionTypeCounts(mcq=1),
            difficulty_mix=DifficultyMix(easy=1.0, medium=0.0, hard=0.0),
            topic_mix=TopicMix(
                mode="manual",
                topics=[TopicEntry(topic_id=t1, question_count=1)],
            ),
        )
        slots = BlueprintService.expand_to_slots(config)
        assert sum(s.count for s in slots) == 1
        assert all(s.topic_id == t1 for s in slots)
