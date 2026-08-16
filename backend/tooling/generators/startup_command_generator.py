"""
启动命令生成器
从 YAML 配置生成 vLLM 启动命令
"""
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class StartupCommandGenerator:
    """vLLM 启动命令生成器"""

    # 参数映射表：YAML 字段名 -> vLLM 命令行参数
    PARAM_MAPPING = {
        "model": "--model",
        "tensor_parallel_size": "--tensor-parallel-size",
        "pipeline_parallel_size": "--pipeline-parallel-size",
        "max_model_len": "--max-model-len",
        "gpu_memory_utilization": "--gpu-memory-utilization",
        "kv_cache_dtype": "--kv-cache-dtype",
        "enable_prefix_caching": "--enable-prefix-caching",
        "max_num_batched_tokens": "--max-num-batched-tokens",
        "max_num_seqs": "--max-num-seqs",
        "served_model_name": "--served-model-name",
        "host": "--host",
        "port": "--port",
        "dtype": "--dtype",
        "load_format": "--load-format",
        "trust_remote_code": "--trust-remote-code",
        "enforce_eager": "--enforce-eager",
        "max_context_len_to_capture": "--max-context-len-to-capture",
        "max_seq_len_to_capture": "--max-seq-len-to-capture",
        "disable_custom_all_reduce": "--disable-custom-all-reduce",
        "tokenizer_mode": "--tokenizer-mode",
        "rope_scaling": "--rope-scaling",
        "rope_theta": "--rope-theta",
        "quantization": "--quantization",
        "max_parallel_loading_workers": "--max-parallel-loading-workers",
        "block_size": "--block-size",
        "swap_space": "--swap-space",
        "num_gpu_blocks_override": "--num-gpu-blocks-override",
        "num_lookahead_slots": "--num-lookahead-slots",
        "model_loader_extra_config": "--model-loader-extra-config",
        "preemption_mode": "--preemption-mode",
        "scheduler_delay_factor": "--scheduler-delay-factor",
        "enable_chunked_prefill": "--enable-chunked-prefill",
        "guided_decoding_backend": "--guided-decoding-backend",
        "speculative_model": "--speculative-model",
        "num_speculative_tokens": "--num-speculative-tokens",
        "speculative_max_model_len": "--speculative-max-model-len",
        "ngram_prompt_lookup_max": "--ngram-prompt-lookup-max",
        "ngram_prompt_lookup_min": "--ngram-prompt-lookup-min",
    }

    # 布尔参数（不需要值）
    BOOLEAN_PARAMS = {
        "enable_prefix_caching",
        "trust_remote_code",
        "enforce_eager",
        "disable_custom_all_reduce",
        "enable_chunked_prefill",
    }

    def __init__(self):
        pass

    def generate_from_yaml(self, config_yaml: str, vllm_version: str | None = None) -> str:
        """
        从 YAML 配置生成启动命令

        Args:
            config_yaml: YAML 格式的配置文件
            vllm_version: vLLM 版本（用于注释）

        Returns:
            完整的 vllm serve 命令
        """
        try:
            import yaml
            config = yaml.safe_load(config_yaml)
        except Exception as e:
            logger.error(f"Failed to parse YAML config: {e}")
            # 尝试作为 JSON 解析
            try:
                config = json.loads(config_yaml)
            except Exception as json_e:
                logger.error(f"Failed to parse as JSON: {json_e}")
                return "# 配置解析失败，请检查 YAML 格式"

        return self.generate_from_dict(config, vllm_version)

    def generate_from_dict(
        self,
        config: dict[str, Any],
        vllm_version: str | None = None
    ) -> str:
        """
        从字典配置生成启动命令

        Args:
            config: 配置字典
            vllm_version: vLLM 版本

        Returns:
            完整的 vllm serve 命令
        """
        # 基础命令
        cmd_parts = ["vllm serve"]

        # 添加版本注释
        if vllm_version:
            cmd_parts.insert(0, f"# vLLM {vllm_version}")

        # 必须参数：model
        model = config.get("model_name") or config.get("model")
        if model:
            cmd_parts.append(f'--model "{model}"')
        else:
            cmd_parts.append("# 错误：缺少 model_name")
            return "\n".join(cmd_parts)

        # 处理其他参数
        for yaml_key, cli_param in self.PARAM_MAPPING.items():
            if yaml_key in config:
                value = config[yaml_key]

                # 跳过 model_name（已处理）
                if yaml_key == "model_name":
                    continue

                # 布尔参数
                if yaml_key in self.BOOLEAN_PARAMS:
                    if value:
                        cmd_parts.append(cli_param)
                else:
                    # 字符串或数字参数
                    if isinstance(value, str):
                        cmd_parts.append(f'{cli_param} "{value}"')
                    elif isinstance(value, (int, float)):
                        cmd_parts.append(f'{cli_param} {value}')
                    elif isinstance(value, bool):
                        if value:
                            cmd_parts.append(cli_param)
                    elif isinstance(value, list):
                        # 列表参数（如 rope_scaling）
                        cmd_parts.append(f'{cli_param} "{json.dumps(value)}"')
                    elif isinstance(value, dict):
                        # 字典参数（如 rope_scaling）
                        cmd_parts.append(f'{cli_param} "{json.dumps(value)}"')

        # 添加 Ascend 特定参数（如果配置中有）
        if config.get("device") == "ascend" or "ascend" in config.get("hardware", "").lower():
            # Ascend 设备特定参数
            if "device" not in config:
                cmd_parts.append('--device "ascend"')

        return " \\\n  ".join(cmd_parts)

    def generate_multi_version(
        self,
        config_yaml: str,
        versions: list[str]
    ) -> dict[str, str]:
        """
        生成多个 vLLM 版本的启动命令

        Args:
            config_yaml: YAML 配置文件
            versions: vLLM 版本列表，如 ["v0.16.0", "v0.17.0"]

        Returns:
            {version: command} 字典
        """
        result = {}
        for version in versions:
            result[version] = self.generate_from_yaml(config_yaml, version)
        return result

    def parse_command_to_dict(self, command: str) -> dict[str, Any]:
        """
        解析启动命令回字典格式（用于编辑）

        Args:
            command: vllm serve 命令字符串

        Returns:
            配置字典
        """
        config = {}

        # 简单的命令行解析
        lines = command.strip().split("\n")
        full_cmd = " ".join(line.strip() for line in lines if not line.strip().startswith("#"))

        # 解析参数
        parts = full_cmd.split()
        i = 0
        while i < len(parts):
            part = parts[i]
            if part.startswith("--"):
                param_name = part[2:]
                # 检查下一个参数是否是值
                if i + 1 < len(parts) and not parts[i + 1].startswith("--"):
                    value = parts[i + 1].strip('"')
                    # 尝试转换为数字
                    try:
                        if "." in value:
                            value = float(value)
                        else:
                            value = int(value)
                    except ValueError:
                        pass
                    config[param_name] = value
                    i += 2
                else:
                    # 布尔参数
                    config[param_name] = True
                    i += 1
            else:
                i += 1

        return config
