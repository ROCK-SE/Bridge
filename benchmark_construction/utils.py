import logging

import requests
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from woc.local import WocMapsLocal

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

woc = WocMapsLocal()

SIMPLE_API_ENDPOINT = "https://pypi.org/simple"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Accept": "application/vnd.pypi.simple.v1+json",
}


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


def read_blob(sha: str) -> str | None:
    """Read a blob's content by it sha1 value."""
    try:
        return woc.show_content("blob", sha)
    except:
        return None


def list_pypi_packages(retry: int = 5) -> list[str] | None:
    """List all PyPI packages with PyPI Simple API

    Parameters
    ----------
    retry : int, optional
        Repeat `requests.get` max `retry` times, by default 5

    Returns
    -------
    list[str] | None
        A list of canonicalize PyPI package names
    """

    while retry > 0:
        packages = []
        r = requests.get(SIMPLE_API_ENDPOINT, headers=HEADERS, timeout=5)
        if r.status_code == requests.codes.ok:
            logger.debug("Request Simple API successfully")
            projects = r.json()["projects"]
            packages = [canonicalize_name(proj["name"]) for proj in projects]
            packages = list(set(packages))
            print(f"{len(packages)} PyPI packages")
            with open("pypi_packages.csv", "w") as outf:
                for pkg in packages:
                    outf.write(f"{pkg}\n")
            return packages

        retry -= 1
        logger.error(
            "Request Simple API successfully", f"retrying...{retry} times left"
        )
