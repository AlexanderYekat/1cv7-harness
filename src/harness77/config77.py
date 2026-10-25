"""Explicit project and stand profiles (TOML); no machine paths in the core.

The project profile describes the sources, the ERT template and the expected
test outcomes. The stand profile describes one local installation: backend,
paths, selected existing base and pinned hashes. Relative paths resolve from the
profile's own directory, not the shell's working directory. Secrets (passwords)
are never stored; machine paths and the base path are redacted from the portable
report and represented by role, basename and a salted-free SHA-256 tag instead.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
import tomllib

from .deadlines77 import Deadlines, PHASES

SCHEMA_VERSION = 1
BACKENDS = ("native", "simulation", "import")
TIMEOUT_KEYS = {"open": "open_timeout_s", "calculation": "calculation_timeout_s",
                "cancel": "cancel_timeout_s", "shutdown": "shutdown_timeout_s",
                "total": "total_timeout_s"}


class ConfigError(ValueError):
    """Readable error for an invalid or incomplete profile."""


def _load_toml(path):
    path = Path(path).resolve(strict=True)
    if not path.is_file():
        raise ConfigError(f"Профиль должен быть файлом TOML: {path}")
    try:
        with path.open("rb") as stream:
            return tomllib.load(stream), path
    except (tomllib.TOMLDecodeError, OSError) as exc:
        raise ConfigError(f"Не прочитан профиль {path}: {exc}") from exc


def _require(table, key, where):
    if key not in table:
        raise ConfigError(f"{where}: отсутствует обязательный ключ '{key}'")
    return table[key]


def _resolve(base_dir, value, where):
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{where}: путь должен быть непустой строкой")
    path = Path(value)
    return path if path.is_absolute() else (base_dir / path)


SCALAR = (str, int, float, bool)


def _parameter(value):
    """A launcher parameter: a scalar, or an array of scalars or of tables of scalars (task 025, steps)."""
    if isinstance(value, SCALAR):
        return True
    return isinstance(value, list) and all(
        isinstance(item, SCALAR) or isinstance(item, dict) and all(isinstance(v, SCALAR) for v in item.values())
        for item in value)


def path_tag(path):
    """Role-free, reversible-free identifier for a local path in the report."""
    text = str(path)
    return {"name": Path(text).name, "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}


@dataclass(frozen=True)
class ProjectProfile:
    path: Path
    project_id: str
    template: Path
    source: Path
    encoding: str
    legacy_normalize: bool
    globals: tuple
    allow: tuple
    strict: bool
    tests: tuple
    deadlines_raw: dict
    # Application parameters for the stand launcher, e.g. a report window.
    parameters: dict = field(default_factory=dict)
    # Form description (task 008); None keeps the template's form.
    form: Path | None = None
    # Visual checks of the form against approved baselines (task 010).
    visual: object | None = None
    # 1Cv7.MD numbering the named kinds of reference fields (task 012); None: the stand base's.
    metadata: Path | None = None
    # Changed modules of the stand base's 1Cv7.MD (task 021, md-extract layout): the run builds the
    # configuration and checks it on a copy of the base; keep_copy leaves the copy in the run.
    configuration: Path | None = None
    keep_copy: bool = False

    def public(self):
        return {"project_id": self.project_id, "profile": path_tag(self.path),
                "template": path_tag(self.template), "source": path_tag(self.source),
                "form": path_tag(self.form) if self.form is not None else None,
                "metadata": path_tag(self.metadata) if self.metadata is not None else None,
                "configuration": ({"modules": path_tag(self.configuration), "keep_copy": self.keep_copy}
                                  if self.configuration is not None else None),
                "encoding": self.encoding, "legacy_normalize": self.legacy_normalize,
                "analysis": {"globals": [path_tag(p) for p in self.globals],
                             "allow": list(self.allow), "strict": self.strict},
                "tests": [dict(t) for t in self.tests], "parameters": dict(self.parameters),
                "visual": self.visual.public() if self.visual is not None else None}

    def commands(self):
        """Commands of the declared tests, in declaration order, without repeats."""
        return list(dict.fromkeys(test["command"] for test in self.tests))


@dataclass(frozen=True)
class StandProfile:
    path: Path
    name: str
    backend: str
    exe: Path | None
    cdb: Path | None
    helper: Path | None
    identity: Path | None
    base: Path
    user: str
    credential_source: str
    platform_version: str
    pinned: dict
    tool_hashes: dict
    deadlines_raw: dict
    scenario: Path | None
    import_protocol: Path | None
    screenshots: bool
    extra: dict = field(default_factory=dict)
    # The copy of the base for a changed configuration (task 021): its one path, registered in
    # 1C's list of bases, and the top-level subdirectories it leaves out.
    copy_path: Path | None = None
    copy_exclude: tuple = ()

    def public(self):
        """Platform and base identity for the report, without secrets or raw paths."""
        block = {"stand": self.name, "backend": self.backend,
                 "platform_version": self.platform_version,
                 "base": path_tag(self.base), "base_usage": "existing-direct-no-copy",
                 **({"copy": path_tag(self.copy_path)} if self.copy_path is not None else {}),
                 "user_present": bool(self.user), "credential_source": self.credential_source,
                 "pinned_hashes": dict(self.pinned), "screenshots_enabled": self.screenshots}
        for role, path in (("exe", self.exe), ("cdb", self.cdb),
                           ("helper", self.helper), ("identity", self.identity)):
            if path is not None:
                block.setdefault("tools", {})[role] = path_tag(path)
        return block


def load_project(path) -> ProjectProfile:
    data, path = _load_toml(path)
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ConfigError(f"{path}: нужна schema_version = {SCHEMA_VERSION}")
    base_dir = path.parent
    project = _require(data, "project", str(path))
    build = _require(data, "build", str(path))
    analysis = data.get("analysis", {})
    platform = data.get("platform", {})
    tests = []
    for index, item in enumerate(platform.get("tests", [])):
        if not isinstance(item, dict) or "name" not in item or "expect" not in item:
            raise ConfigError(f"{path}: тест #{index} требует 'name' и 'expect'")
        if item["expect"] not in ("passed", "failed", "blocked"):
            raise ConfigError(f"{path}: тест '{item['name']}' имеет неизвестный expect")
        test = {"name": str(item["name"]), "expect": item["expect"],
                "command": str(item.get("command", item["name"])),
                "description": str(item.get("description", ""))}
        if "expect_value" in item:
            test["expect_value"] = str(item["expect_value"])
        tests.append(test)
    parameters = platform.get("parameters", {})
    if not isinstance(parameters, dict) or not all(_parameter(value) for value in parameters.values()):
        raise ConfigError(f"{path}: [platform.parameters] допускает строки, числа, логические значения "
                          "и массивы из них или из таблиц таких значений")
    visual = None
    if "visual" in data:
        from .visual77 import VisualError, parse_config
        try:
            visual = parse_config(data["visual"], base_dir)
        except VisualError as error:
            raise ConfigError(f"{path}: {error}") from None
    configuration = data.get("configuration")
    if configuration is not None:
        if not isinstance(configuration, dict) or set(configuration) - {"modules", "keep_copy"}:
            raise ConfigError(f"{path}: [configuration] допускает только modules и keep_copy")
        if not isinstance(configuration.get("keep_copy", False), bool):
            raise ConfigError(f"{path}: configuration.keep_copy — логическое значение")
    return ProjectProfile(
        path=path, project_id=str(_require(project, "id", "project")),
        template=_resolve(base_dir, _require(build, "template", "build"), "build.template"),
        source=_resolve(base_dir, _require(build, "source", "build"), "build.source"),
        encoding=str(build.get("encoding", "auto")),
        legacy_normalize=bool(build.get("legacy_normalize", False)),
        globals=tuple(_resolve(base_dir, g, "analysis.globals") for g in analysis.get("globals", [])),
        allow=tuple(str(a) for a in analysis.get("allow", [])),
        strict=bool(analysis.get("strict", False)),
        tests=tuple(tests), deadlines_raw=dict(data.get("deadlines", {})), parameters=dict(parameters),
        form=_resolve(base_dir, build["form"], "build.form") if "form" in build else None, visual=visual,
        metadata=_resolve(base_dir, build["metadata"], "build.metadata") if "metadata" in build else None,
        configuration=(_resolve(base_dir, _require(configuration, "modules", "configuration"), "configuration.modules")
                       if configuration is not None else None),
        keep_copy=bool((configuration or {}).get("keep_copy", False)))


def load_stand(path) -> StandProfile:
    data, path = _load_toml(path)
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ConfigError(f"{path}: нужна schema_version = {SCHEMA_VERSION}")
    base_dir = path.parent
    stand = _require(data, "stand", str(path))
    backend = _require(stand, "backend", "stand")
    if backend not in BACKENDS:
        raise ConfigError(f"stand.backend должен быть одним из {BACKENDS}")
    paths = stand.get("paths", {})
    base_table = _require(stand, "base", "stand")
    if "password" in stand or "password" in base_table:
        raise ConfigError("stand: пароли не хранятся в профиле; используйте пустой пароль по разрешению владельца")

    def optional(role):
        return _resolve(base_dir, paths[role], f"stand.paths.{role}") if role in paths else None

    scenario = _resolve(base_dir, stand["scenario"], "stand.scenario") if "scenario" in stand else None
    import_protocol = (_resolve(base_dir, stand["import_protocol"], "stand.import_protocol")
                       if "import_protocol" in stand else None)
    if backend == "simulation" and scenario is None:
        raise ConfigError("stand.backend=simulation требует 'scenario'")
    if backend == "import" and import_protocol is None:
        raise ConfigError("stand.backend=import требует 'import_protocol'")
    exclude = base_table.get("copy_exclude", [])
    if not isinstance(exclude, list) or not all(
            isinstance(name, str) and name.strip(". ") and not any(c in name for c in '/\\:') for name in exclude):
        raise ConfigError("stand.base.copy_exclude — список имён подкаталогов базы верхнего уровня")
    return StandProfile(
        path=path, name=str(_require(stand, "name", "stand")), backend=backend,
        exe=optional("exe"), cdb=optional("cdb"), helper=optional("helper"), identity=optional("identity"),
        base=_resolve(base_dir, _require(base_table, "path", "stand.base"), "stand.base.path"),
        user=str(base_table.get("user", "")),
        credential_source=str(stand.get("credential_source", "empty password authorized by owner; not stored")),
        platform_version=str(stand.get("platform_version", "")),
        pinned=dict(stand.get("pinned", {})), tool_hashes=dict(stand.get("tool_hashes", {})),
        deadlines_raw=dict(data.get("deadlines", {})), scenario=scenario, import_protocol=import_protocol,
        screenshots=bool(stand.get("screenshots", False)), copy_exclude=tuple(exclude),
        copy_path=(_resolve(base_dir, base_table["copy_path"], "stand.base.copy_path")
                   if "copy_path" in base_table else None),
        extra={k: v for k, v in stand.items() if k not in (
            "name", "backend", "paths", "base", "credential_source", "platform_version",
            "pinned", "tool_hashes", "scenario", "import_protocol", "screenshots")})


def resolve_deadlines(project: ProjectProfile, stand: StandProfile, overrides=None) -> Deadlines:
    """Merge stand < project < CLI; every phase must be explicit (no 30/145 default)."""
    overrides = overrides or {}
    values, sources = {}, {}
    for phase, key in TIMEOUT_KEYS.items():
        if key in overrides and overrides[key] is not None:
            values[phase], sources[phase] = overrides[key], "cli"
        elif key in project.deadlines_raw:
            values[phase], sources[phase] = project.deadlines_raw[key], "project"
        elif key in stand.deadlines_raw:
            values[phase], sources[phase] = stand.deadlines_raw[key], "stand"
        else:
            raise ConfigError(
                f"срок '{key}' не задан (ни CLI, ни профиль проекта, ни стенд); "
                "умолчаний нет, прототипные 30/145 с не применяются")
    # Optional: extra open time used only after an interrupted session (task 007).
    reindex = 0.0
    for source, table in (("cli", overrides), ("project", project.deadlines_raw), ("stand", stand.deadlines_raw)):
        if table.get("reindex_timeout_s") is not None:
            reindex, sources["reindex"] = table["reindex_timeout_s"], source
            break
    return Deadlines.create(open_s=values["open"], calculation_s=values["calculation"],
                            cancel_s=values["cancel"], shutdown_s=values["shutdown"],
                            total_s=values["total"], sources=sources, reindex_s=reindex)
