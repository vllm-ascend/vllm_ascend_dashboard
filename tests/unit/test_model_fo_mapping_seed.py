from tooling.model_fo_mapping import normalize_model_key
from tooling.parsers.nightly_config_parser import load_model_fo_map


def test_model_fo_seed_contains_merged_main_entries() -> None:
    mappings = load_model_fo_map()

    assert mappings["GLM-4.7.yaml"] == "游致远"
    assert mappings["Qwen3-30B-QuaRot-eagle3.yaml"] == "董钰彬"
    assert mappings["DeepSeek-V4-Pro-w4a8-prefix-cache-PD.yaml"] == "陈梦龙"
    assert normalize_model_key("GLM-4.7.yaml") == "glm-4.7"
