"""Tests for grant type mapping configuration consistency."""

import yaml
from pathlib import Path


_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "grant_type_mapping.yml"


def _load_mapping() -> dict:
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class TestGrantTypeMappingConfig:
    """Tests for grant_type_mapping.yml structure and completeness."""

    def test_config_loads(self):
        mapping = _load_mapping()
        assert "grant_type_buckets" in mapping

    def test_all_buckets_present(self):
        mapping = _load_mapping()
        expected = {
            "fellowship", "project", "programme", "seed",
            "studentship", "infrastructure", "centre", "travel", "other",
        }
        actual = set(mapping["grant_type_buckets"].keys())
        assert actual == expected

    def test_each_bucket_has_label(self):
        mapping = _load_mapping()
        for bucket_key, bucket_cfg in mapping["grant_type_buckets"].items():
            assert "label" in bucket_cfg, f"Missing label for {bucket_key}"

    def test_each_bucket_has_target_flag(self):
        mapping = _load_mapping()
        for bucket_key, bucket_cfg in mapping["grant_type_buckets"].items():
            assert "target" in bucket_cfg, f"Missing target flag for {bucket_key}"

    def test_target_buckets(self):
        mapping = _load_mapping()
        targets = [
            k for k, v in mapping["grant_type_buckets"].items()
            if v.get("target", False)
        ]
        assert set(targets) == {"fellowship", "project", "programme"}

    def test_each_bucket_has_patterns_list(self):
        mapping = _load_mapping()
        for bucket_key, bucket_cfg in mapping["grant_type_buckets"].items():
            assert "patterns" in bucket_cfg, f"Missing patterns for {bucket_key}"
            assert isinstance(bucket_cfg["patterns"], list), f"Patterns not a list for {bucket_key}"

    def test_patterns_are_valid_regex(self):
        import re
        mapping = _load_mapping()
        for bucket_key, bucket_cfg in mapping["grant_type_buckets"].items():
            for pattern in bucket_cfg.get("patterns", []):
                try:
                    re.compile(pattern)
                except re.error as exc:
                    pytest.fail(f"Invalid regex in {bucket_key}: {pattern!r} -- {exc}")
