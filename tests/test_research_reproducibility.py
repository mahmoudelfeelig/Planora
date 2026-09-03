from __future__ import annotations

import hashlib
import json

from core.metaheuristics import LocalSearchImprover
from utils.generator import generate_instance, instance_to_json


def _instance_hash(mode: str, seed: int) -> str:
    payload = json.dumps(
        instance_to_json(generate_instance(mode, seed=seed)),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def test_generator_seed_is_effective_and_reproducible_for_named_presets() -> None:
    first = _instance_hash("small_demo", 101)
    assert first == _instance_hash("small_demo", 101)
    assert first != _instance_hash("small_demo", 102)


def test_generator_seed_is_effective_and_reproducible_for_random_mode() -> None:
    first = _instance_hash("random", 201)
    assert first == _instance_hash("random", 201)
    assert first != _instance_hash("random", 202)


def test_local_search_owns_a_seeded_random_stream() -> None:
    inst = generate_instance("small_demo", seed=303)
    first = LocalSearchImprover(inst, random_seed=17)
    second = LocalSearchImprover(inst, random_seed=17)
    different = LocalSearchImprover(inst, random_seed=18)

    first_values = [first._rng.random() for _ in range(8)]
    assert first_values == [second._rng.random() for _ in range(8)]
    assert first_values != [different._rng.random() for _ in range(8)]
