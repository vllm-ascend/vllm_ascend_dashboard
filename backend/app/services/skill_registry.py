import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SkillInfo:
    name: str
    description: str
    scope: str | None = None
    content: str = ""
    file_path: str = ""
    loaded_at: str = ""


class SkillRegistry:

    def __init__(self):
        self._skills: dict[str, SkillInfo] = {}
        self._builtin_dir = self._resolve_builtin_skills_dir()
        self._data_dir: Path = self._resolve_data_skills_dir()
        self._load_all()

    def _resolve_builtin_skills_dir(self) -> Path:
        project_root = Path(__file__).parent.parent.parent.parent
        agents_skills_dir = project_root / ".agents" / "skills"
        if agents_skills_dir.exists():
            return agents_skills_dir
        fallback = Path(__file__).parent.parent / "resources" / "skills"
        if fallback.exists():
            logger.info(f"Builtin skills dir not found at {agents_skills_dir}, falling back to {fallback}")
            return fallback
        return agents_skills_dir

    def _resolve_data_skills_dir(self) -> Path:
        from app.core.config import settings
        data_dir = settings.DATA_DIR
        skills_dir = Path(data_dir) / "skills"
        if not skills_dir.is_absolute():
            skills_dir = Path(os.getcwd()) / skills_dir
        return skills_dir

    def _load_all(self):
        self._skills.clear()
        for skill_dir in self._builtin_dir.iterdir():
            if skill_dir.is_dir():
                skill_file = skill_dir / "SKILL.md"
                if skill_file.exists():
                    self._load_skill_file(skill_dir.name, skill_file, "builtin")
        if self._data_dir.exists():
            for skill_dir in self._data_dir.iterdir():
                if skill_dir.is_dir():
                    skill_file = skill_dir / "SKILL.md"
                    if skill_file.exists():
                        self._load_skill_file(skill_dir.name, skill_file, "data")
        logger.info(f"Loaded {len(self._skills)} skills from builtin + data directories")

    def _load_skill_file(self, skill_name: str, skill_file: Path, source: str):
        try:
            content = skill_file.read_text(encoding="utf-8")
            metadata, body = self._parse_frontmatter(content)
            info = SkillInfo(
                name=metadata.get("name", skill_name),
                description=metadata.get("description", ""),
                scope=metadata.get("scope"),
                content=body,
                file_path=str(skill_file),
                loaded_at=self._timestamp(),
            )
            self._skills[skill_name] = info
            logger.info(f"Skill loaded: {skill_name} (scope={info.scope}, source={source})")
        except Exception as e:
            logger.error(f"Failed to load skill {skill_name} from {source}: {e}")

    @staticmethod
    def _parse_frontmatter(content: str) -> tuple[dict[str, str], str]:
        if not content.startswith("---"):
            return {}, content
        end = content.find("---", 3)
        if end == -1:
            return {}, content
        meta_block = content[3:end].strip()
        body = content[end + 3:].strip()
        metadata: dict[str, str] = {}
        for line in meta_block.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                metadata[key.strip()] = value.strip().strip('"').strip("'")
        return metadata, body

    @staticmethod
    def _timestamp() -> str:
        from datetime import UTC, datetime
        return datetime.now(UTC).isoformat()

    def get_skill(self, skill_name: str) -> SkillInfo | None:
        return self._skills.get(skill_name)

    def get_skill_by_scope(self, scope: str) -> SkillInfo | None:
        for info in self._skills.values():
            if info.scope == scope:
                return info
        return None

    def list_skills(self) -> list[SkillInfo]:
        return list(self._skills.values())

    def refresh(self):
        self._load_all()
        return len(self._skills)


_registry: SkillRegistry | None = None


def get_skill_registry() -> SkillRegistry:
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
    return _registry


def refresh_skill_registry() -> int:
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
        return len(_registry._skills)
    return _registry.refresh()
