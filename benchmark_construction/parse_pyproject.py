import tomllib

from utils import parse_reqs


def parse_deps(reqs: list[str], extras_req: dict[str, list]) -> dict[str, str]:
    dependencies = {}

    for name, constraint in parse_reqs(reqs).items():
        dependencies[name] = dependencies.get(name, constraint)

    for reqs in extras_req.values():
        for name, constraint in parse_reqs(reqs).items():
            dependencies[name] = dependencies.get(name, constraint)

    return dependencies


def pep621_parser(pp_toml: dict) -> dict[str, str]:
    """Parse dependencies from the pyproject.toml according to [the pyproject.toml specification](https://packaging.python.org/en/latest/specifications/pyproject-toml/)."""
    project_table = pp_toml.get("project", {})
    reqs = project_table.get("dependencies", [])
    optional_dependencies = project_table.get("optional-dependencies", {})
    return parse_deps(reqs, optional_dependencies)


def flit_parser(pp_toml: dict) -> dict[str, str]:
    """Parse dependencies from pyproject.toml based on [Flit's pyproject.toml specification](https://flit.pypa.io/en/stable/pyproject_toml.html). Flit provides two ways to specify metadata, the newer one via a [project] table and the older one via a [tool.flit.metadata] table along with [tool.flit.scripts] and [tool.flit.entrypoints]. But Flit does not allow to mix them"""
    tool_flit = pp_toml.get("tool", {}).get("flit", {})
    if "project" in pp_toml:
        # Can not mix the two ways
        if "metadata" in tool_flit:
            return {}
        elif ("scripts" in tool_flit) or ("entrypoints" in tool_flit):
            return {}

        return pep621_parser(pp_toml)

    elif "metadata" in tool_flit:
        # The [tool.flit.module] can be only used with the [project] table
        if "module" in tool_flit:
            return {}
        md_sect = tool_flit["metadata"]
        requires = md_sect.get("requires", [])
        requires_extra = md_sect.get("requires-extra", {})
        return parse_deps(requires, requires_extra)

    return {}


def convert_single_caret(req: str) -> str:
    req = "".join(req.split())
    if req == "^0":
        return ">=0.0.0 <1.0.0"
    if req == "^0.0":
        return ">=0.0.0 <0.1.0"
    try:
        specifier = req[1:].split(".", 2)
        specifier = specifier + (3 - len(specifier)) * ["0"]
        low = ".".join(specifier)
        if specifier[0] != "0":
            high = f"{int(specifier[0]) + 1}.0.0"
            return f">={low},<{high}"
        if specifier[1] == "0":
            if specifier[2] != "0":
                return f"=={low}"
        else:
            high = f"0.{int(specifier[1]) + 1}.0"
            return f">={low},<{high}"
    except:
        return req


def convert_single_tilde(req: str) -> str:
    req = "".join(req.split())
    specifier = req[1:].split(".", 2)
    cnt = len(specifier)
    specifier = specifier + (3 - len(specifier)) * ["0"]
    low = ".".join(specifier)
    try:
        if cnt >= 2:
            high = f"{specifier[0]}.{int(specifier[1])+1}.0"
            return f">={low},<{high}"
        else:
            return f">={low},<{int(specifier[0])+1}.0.0"
    except:
        return req


def convert_caret_tilde(req: str) -> str:
    """Convert the caret requirement and tilde requirement supported by poetry to the requirements in PEP508."""
    req = "".join(req.split())
    parts = req.split(",")
    res = []
    for p in parts:
        if p == "*":
            continue
        elif p.startswith("^"):
            res.append(convert_single_caret(p))
        elif p.startswith("~") and (not p.startswith("~=")):
            res.append(convert_single_tilde(p))
        else:
            res.append(p)
    return ",".join(res)


def parse_poetry_dependencies(
    poetry_reqs: dict,
) -> tuple[dict[str, str], dict[str, str]]:
    reqs, optional_reqs = [], []
    for name, constraints in poetry_reqs.items():
        # Poetry support declaring python version in the [tool.poetry.dependencies] table
        if name.lower() == "python":
            continue

        # Poetry support declaring multiple constraint dependencies in the [tool.poetry.dependencies] table
        # We do not consider such dependencies to ensure the accuracy
        if isinstance(constraints, list):
            continue

        if isinstance(constraints, dict):
            # Skip dependencies beyond PyPI
            if any(s in constraints for s in ["git", "path", "url", "source"]):
                continue
            # Poetry supports caret requirements and tilde requirements, which are not supported
            # by PEP 508. We do not parse these two types of requirements for the sake of speed
            # since we have to process millions of files.
            spec = constraints.get("version", "")
            spec = convert_caret_tilde(spec)
            if constraints.get("optional"):
                optional_reqs.append(f"{name}{spec}")
            else:
                reqs.append(f"{name}{spec}")
        elif isinstance(constraints, str):
            spec = convert_caret_tilde(constraints)
            reqs.append(f"{name}{spec}")

    return parse_reqs(reqs), parse_reqs(optional_reqs)


def poetry_parser(pp_toml: dict) -> dict[str, str]:
    try:
        project_table = pp_toml.get("project", {})

        # parse dependencies in [project] table
        dependencies = {}
        reqs = project_table.get("dependencies", [])
        for name, constraint in parse_reqs(reqs).items():
            dependencies[name] = dependencies.get(name, constraint)

        # parse optional dependencies in [project] table
        optional_dependencies = {}
        extras_req = project_table.get("optional-dependencies", {})
        for reqs in extras_req.values():
            for name, constraint in parse_reqs(reqs).items():
                optional_dependencies[name] = dependencies.get(name, constraint)

        # parse dependencies and optional dependencies in [project] table
        tool_poetry = pp_toml.get("tool", {}).get("poetry", {})
        poetry_reqs = tool_poetry.get("dependencies", {})
        poetry_dependencies, optional_poetry_dependencies = parse_poetry_dependencies(
            poetry_reqs
        )

        results = {}
        if (not dependencies) and (not optional_dependencies):
            results.update(poetry_dependencies)
            results.update(optional_poetry_dependencies)
            return results

        # determine final dependencies by the dynamic field
        dynamic = project_table.get("dynamic", [])
        if "dependencies" in dynamic:
            results.update(poetry_dependencies)
        else:
            results.update(dependencies)

        if "optional-dependencies" in dynamic:
            results.update(optional_poetry_dependencies)
        else:
            results.update(optional_dependencies)

        return results
    except Exception as e:
        return {}


# Build backends listed in [the Tool recommendations page of the Python Packaging User Guide](https://packaging.python.org/en/latest/guides/tool-recommendations/#build-backends)
VALID_BUILD_BACKEND = {
    # [Setuptools](https://setuptools.pypa.io/en/latest/userguide/pyproject_config.html)
    # setuptools also supports specifying dependencies and optional-dependencies using the file directive
    # in the dynamic field. Here, we do not deal with this case, since we will deal with requirements.txt
    # which is often the parameter of the file directive
    "setuptools.build_meta": pep621_parser,
    # [Flit-core](https://flit.pypa.io/en/stable/pyproject_toml.html)
    "flit_core.buildapi": flit_parser,
    # [Hatchling](https://hatch.pypa.io/latest/config/build/)
    "hatchling.build": pep621_parser,
    # [PDM-backend](https://backend.pdm-project.org/)
    "pdm.backend": pep621_parser,
    # [Poetry-core](https://python-poetry.org/docs/pyproject/#poetry-and-pep-517)
    "poetry.core.masonry.api": poetry_parser,
    "poetry.masonry.api": poetry_parser,
    # [meson-python](https://mesonbuild.com/meson-python/)
    "mesonpy": pep621_parser,
    # [scikit-build-core](https://scikit-build-core.readthedocs.io/en/latest/getting_started.html#python-package-configuration)
    "scikit_build_core.build": pep621_parser,
    # [Maturin](https://www.maturin.rs/#source-distribution)
    "maturin": pep621_parser,
}


def get_build_backend(pp_toml: dict) -> str | None:
    build_system = pp_toml.get("build-system")
    if build_system is None:
        # default build backend: setuptools
        return "setuptools.build_meta"
    build_backend = build_system.get("build-backend")
    if build_backend is None:
        return "setuptools.build_meta"
    # We only consider build backends in VALID_BUILD_BACKEND
    if build_backend not in VALID_BUILD_BACKEND:
        return None
    return build_backend


def parse_pyproject_toml(content: str) -> dict[str, str]:
    try:
        pp_toml = tomllib.loads(content)
        build_backend = get_build_backend(pp_toml)
        if build_backend is None:
            return {}
        parser = VALID_BUILD_BACKEND[build_backend]
        return parser(pp_toml)
    except:
        return {}
