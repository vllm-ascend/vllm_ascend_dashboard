"""
解析 vllm-ascend 代码仓中的 .github/workflows/configs/nightly_config.yaml，
提取测试用例定义，同步到 nightly_test_cases 表。
"""
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

DEFAULT_REPO_PATH = os.environ.get("VLLM_ASCEND_REPO_PATH", "")
if not DEFAULT_REPO_PATH:
    candidates = [
        Path(__file__).resolve().parent.parent.parent.parent.parent / "vllm-ascend",
        Path("/app/data/vllm-ascend"),
    ]
    for p in candidates:
        if p.exists():
            DEFAULT_REPO_PATH = str(p)
            break

CONFIG_PATH = ".github/workflows/configs/nightly_config.yaml"

# hardware → workflow_name 映射
HARDWARE_WF = {"a2": "Nightly-A2", "a3": "Nightly-A3", "a3-560t": "Nightly-A3", "310p": "Nightly-310P"}

# section → deployment_type 映射
SECTION_DEPLOY = {
    "single_node": "single-node",
    "multi_card": "single-node",
    "double_node": "multi-node-2",
}


@dataclass
class TestCaseDef:
    """从 nightly_config.yaml 解析出的用例定义"""
    name: str                # 用例唯一名
    workflow: str            # Nightly-A2 / Nightly-A3 / Nightly-310P
    hardware: str            # a2 / a3 / a3-560t / 310p
    section: str             # single_node / multi_node / double_node / multi_card / accuracy
    deployment: str          # single-node / multi-node-N
    model_path: str = ""     # 关联的 YAML config 或测试路径
    runner_os: str = ""      # runner 标签
    size: int = 1            # 节点数


def load_model_fo_map() -> dict[str, str]:
    """加载 data/model_fo_map.json 中的模型→FO映射"""
    fo_file = Path(__file__).resolve().parent.parent.parent.parent / "data" / "model_fo_map.json"
    if not fo_file.exists():
        return {}
    try:
        with open(fo_file, encoding="utf-8") as f:
            data = json.load(f)
        return {k: v for k, v in data.items() if not k.startswith("_") and isinstance(v, str)}
    except Exception:
        return {}


class NightlyConfigParser:
    """解析 nightly_config.yaml"""

    def __init__(self, repo_path: str | None = None):
        self.repo_path = Path(repo_path or DEFAULT_REPO_PATH)
        self.config_file = self.repo_path / CONFIG_PATH

    @property
    def is_available(self) -> bool:
        return self.config_file.exists()

    def checkout_branch(self, branch: str) -> bool:
        """切换到指定分支，返回是否成功。支持 origin/ 和 upstream/ 前缀。"""
        import subprocess
        env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
        try:
            # 如果分支在 origin 或 upstream 远程存在，创建本地 tracking branch
            for remote in ["origin", "upstream"]:
                ref = f"{remote}/{branch}"
                r = subprocess.run(
                    ["git", "-C", str(self.repo_path), "rev-parse", "--verify", ref],
                    capture_output=True, text=True, timeout=10, env=env,
                )
                if r.returncode == 0:
                    # 创建/更新本地分支跟踪远程
                    subprocess.run(
                        ["git", "-C", str(self.repo_path), "fetch", remote, branch],
                        capture_output=True, text=True, timeout=30, env=env,
                    )
                    subprocess.run(
                        ["git", "-C", str(self.repo_path), "checkout", "-B", branch, ref],
                        capture_output=True, text=True, timeout=30, env=env,
                    )
                    return True
            # 本地分支直接 checkout
            subprocess.run(
                ["git", "-C", str(self.repo_path), "checkout", branch],
                capture_output=True, text=True, timeout=30, env=env,
            )
            return True
        except Exception as e:
            logger.warning(f"Failed to checkout branch {branch}: {e}")
            return False

    def get_active_branches(self) -> list[str]:
        """获取所有 release 分支（origin + upstream 远程）"""
        import subprocess
        env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
        branches = set()
        for remote in ["origin", "upstream"]:
            try:
                result = subprocess.run(
                    ["git", "-C", str(self.repo_path), "branch", "-r", "--list", f"{remote}/releases/*"],
                    capture_output=True, text=True, timeout=10, env=env,
                )
                for line in result.stdout.strip().split("\n"):
                    line = line.strip()
                    if line and "->" not in line:
                        # 去掉 remote/ 前缀
                        name = line.split("/", 1)[1] if "/" in line else line
                        branches.add(name)
            except Exception:
                pass
        return sorted(branches)

    def parse(self, report_date: str = "", source_branch: str = "main") -> list[TestCaseDef]:
        """解析 nightly_config.yaml，返回用例定义列表"""
        if not self.is_available:
            logger.warning(f"Config file not found: {self.config_file}")
            return []

        with open(self.config_file, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not data:
            return []

        results: list[TestCaseDef] = []
        seen: set[tuple[str, str]] = set()

        for hw_key in ["a2", "a3", "a3-560t", "310p"]:
            hw_data = data.get(hw_key)
            if not hw_data:
                continue
            wf = HARDWARE_WF.get(hw_key, f"Nightly-{hw_key}")

            for section in ["single_node", "multi_node", "double_node", "multi_card", "accuracy"]:
                sec_data = hw_data.get(section)
                if not sec_data:
                    continue

                # 多个 test_config 来源
                test_configs = sec_data.get("test_config", [])
                if not test_configs:
                    test_configs = []

                # accuracy 部分有 nightly / pr_only 子分组
                if section == "accuracy":
                    for sub in ["nightly", "pr_only"]:
                        for tc in sec_data.get(sub, []):
                            if isinstance(tc, dict):
                                for model in tc.get("model_list", []):
                                    key = (wf, f"accuracy-{tc['name']}-{model}")
                                    if key not in seen:
                                        seen.add(key)
                                        results.append(TestCaseDef(
                                            name=key[1],
                                            workflow=wf,
                                            hardware=hw_key,
                                            section=section,
                                            deployment="single-node",
                                            model_path=model,
                                            runner_os=tc.get("os", ""),
                                        ))
                    continue

                deploy = SECTION_DEPLOY.get(section, "single-node")

                for tc in test_configs:
                    if not isinstance(tc, dict):
                        continue
                    name = tc.get("name", "")
                    if not name:
                        continue
                    size = tc.get("size", 1) if "multi_node" in section or "double_node" in section else 1
                    if section in ("multi_node", "double_node"):
                        deploy = f"multi-node-{size}"

                    model_path = tc.get("config_file_path", "") or tc.get("tests", "")
                    key = (wf, name)
                    if key not in seen:
                        seen.add(key)
                        results.append(TestCaseDef(
                            name=name,
                            workflow=wf,
                            hardware=hw_key,
                            section=section,
                            deployment=deploy,
                            model_path=model_path,
                            runner_os=tc.get("os", ""),
                            size=size,
                        ))

        return sorted(results, key=lambda c: (c.workflow, c.name))

    def get_repo_info(self) -> dict:
        return {
            "repo_path": str(self.repo_path),
            "config_file": str(self.config_file),
            "available": self.is_available,
        }
