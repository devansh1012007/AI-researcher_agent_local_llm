# Phase 7 dataset/versioning tests (§7/§8/§9/§19/§32/§33)
from research_engine.learning.eligibility import EligibilityFilter
from research_engine.learning.persistence import LearningDB

def test_eligibility_excludes_synthetic():
    f = EligibilityFilter({"allow_synthetic": False})
    assert not f.is_eligible({"provenance_type": "synthetic", "id": "x", "fingerprint": "f"})

def test_eligibility_includes_real():
    f = EligibilityFilter()
    assert f.is_eligible({"provenance_type": "real", "id": "x", "fingerprint": "f", "observation_time": "2026-01-01"})

def test_filter_duplicates():
    f = EligibilityFilter()
    obs = [{"id":"o1","fingerprint":"f1","provenance_type":"real","observation_time":"2026-01-01"},
           {"id":"o2","fingerprint":"f1","provenance_type":"real","observation_time":"2026-01-01"}]
    eligible, excluded = f.filter_observations(obs)
    assert len(eligible) == 1
    assert excluded["duplicate"] == 1

def test_dataset_snapshot_immutable_fingerprint():
    db = LearningDB("/tmp/phase7_ds_test")
    db.save_dataset_snapshot({"snapshot_id":"s1","fingerprint":"abc","creation_ts":"2026-01-01"})
    s = db.get_dataset_snapshot("s1")
    assert s["fingerprint"] == "abc"
