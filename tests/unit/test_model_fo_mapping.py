from tooling.model_fo_mapping import (
    lookup_model_fo,
    model_key_candidates,
    normalize_model_key,
)


def test_model_key_candidates_support_path_basename_and_stem():
    assert model_key_candidates("configs\\DeepSeek-R1-W8A8.yaml") == (
        "configs/deepseek-r1-w8a8.yaml",
        "deepseek-r1-w8a8.yaml",
        "deepseek-r1-w8a8",
    )


def test_normalize_model_key_uses_case_insensitive_basename():
    assert normalize_model_key("configs/DeepSeek-R1-W8A8.yaml") == "deepseek-r1-w8a8.yaml"


def test_lookup_model_fo_prefers_basename_and_accepts_extensionless_mapping():
    mapping = {
        "deepseek-r1-w8a8": "张三",
        "other.yaml": "李四",
    }

    assert lookup_model_fo(mapping, "configs/DeepSeek-R1-W8A8.yaml") == "张三"
    assert lookup_model_fo(mapping, "other.yaml") == "李四"
    assert lookup_model_fo(mapping, "missing.yaml") is None
