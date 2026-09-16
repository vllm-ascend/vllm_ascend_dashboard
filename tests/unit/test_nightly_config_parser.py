from tooling.parsers.nightly_config_parser import NightlyConfigParser


def test_parser_materializes_a5_cases_for_nightly_a5() -> None:
    cases = NightlyConfigParser.parse_content(
        """
a5:
  single_node:
    test_config:
      - name: a5-smoke
        config_file_path: configs/a5-smoke.yaml
        os: linux-aarch64-a5-8
"""
    )

    assert len(cases) == 1
    case = cases[0]
    assert case.workflow == "Nightly-A5"
    assert case.hardware == "a5"
    assert case.name == "a5-smoke"
