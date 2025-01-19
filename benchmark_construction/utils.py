from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name


def parse_reqs(reqs: list[str]) -> dict[str, str]:
    """Parse a list of requirement specifier strings into (name, version constraints) format.

    Parameters
    ----------
    reqs : list[str]
         a list with each item an requirement specifier string

    Returns
    -------
    dict[str, str]
        a dict with the key as the dependency's name and the key as the dependency's version constraint
    """
    dependencies: dict[str, str] = {}
    for req in reqs:
        # skip the comment
        if req.startswith("#"):
            continue
        try:
            req = Requirement(req)
            # The existence of url suggests that this package is not from PyPI,
            # therefore we skip it.
            if req.url is not None:
                continue
            name = canonicalize_name(req.name)
            specifier = str(req.specifier) if req.specifier else ""
            dependencies[name] = specifier
        except InvalidRequirement:
            pass
    return dependencies
