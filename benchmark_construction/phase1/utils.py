import logging
import os
import random
import time
import urllib.request

import pymongo
import requests
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from pymongo.collection import Collection
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
            # The existence of url suggests that this library is not from PyPI,
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


def list_pypi_libraries(retry: int = 5) -> list[str] | None:
    """List all PyPI libraries with PyPI Simple API

    Parameters
    ----------
    retry : int, optional
        Repeat `requests.get` max `retry` times, by default 5

    Returns
    -------
    list[str] | None
        A list of canonicalize PyPI library names
    """

    while retry > 0:
        packalibrariesges = []
        r = requests.get(SIMPLE_API_ENDPOINT, headers=HEADERS, timeout=5)
        if r.status_code == requests.codes.ok:
            logger.debug("Request Simple API successfully")
            projects = r.json()["projects"]
            libraries = [canonicalize_name(proj["name"]) for proj in projects]
            libraries = list(set(libraries))
            print(f"{len(libraries)} PyPI libraries")
            with open("../../benchmark/Phase1/all_pypi_libraries.csv", "w") as outf:
                for pkg in libraries:
                    outf.write(f"{pkg}\n")
            return libraries

        retry -= 1
        logger.error(
            "Request Simple API successfully", f"retrying...{retry} times left"
        )


# Non-GitHub platforms that WoC collects
URL_PREFIXES = [
    "gitlab.com",
    "bitbucket.org",
    "0xacab.org",
    "android.googlesource.com",
    "bioconductor.org",
    "blitiri.com.ar",
    "code.ill.fr",
    "code.qt.io",
    "drupal.com",
    "fedorapeople.org",
    "forgemia.inra.fr",
    "framagit.org",
    "gcc.git",
    "git.alpinelinux.org",
    "git.debian.org",
    "git.eclipse.org",
    "git.kernel.org",
    "git.openembedded.org",
    "git.pleroma.social",
    "git.postgresql.org",
    "git.savannah.gnu.org",
    "git.savannah.nongnu.org",
    "git.torproject.org",
    "git.unicaen.fr",
    "git.unistra.fr",
    "git.xfce.org",
    "git.yoctoproject.org",
    "git.zx2c4.com",
    "gitbox.apache.org",
    "gite.lirmm.fr",
    "gitlab.adullact.net",
    "gitlab.cerema.fr",
    "gitlab.common-lisp.net",
    "gitlab.fing.edu.uy",
    "gitlab.freedesktop.org",
    "gitlab.gnome.org",
    "gitlab.huma-num.fr",
    "gitlab.inria.fr",
    "gitlab.irstea.fr",
    "gitlab.ow2.org",
    "invent.kde.org",
    "kde.org",
    "notabug.org",
    "pagure.io",
    "repo.or.cz",
    "salsa.debian.org",
    "sourceforge.net",
]


def normalize_url(url: str) -> str:
    """Normalize an url by lowercasing all characters and removing `/` and `.git` suffixes."""
    url = url.lower().strip("/")
    if url.endswith(".git"):
        url = url[:-4]
    return url


def restore_url(woc_uri: str) -> str | None:
    """Convert a woc uri to corresponsing GitHub repository URL"""
    if woc_uri.count("_") < 1:
        return
    prefix = woc_uri.split("_", 1)[0]
    if prefix not in URL_PREFIXES:
        url = f"https://github.com/" + woc_uri.replace("_", "/", 1)
        return normalize_url(url)


def is_strict_ver(identifier: str):
    parts = identifier.split(".")
    if len(parts) > 3:
        return False
    if all(p.isnumeric() for p in parts):
        return True
    return False


def download(
    url: str, save_path: str, check: bool = True, size: int = -1, max_try=3
) -> bool:
    if check and os.path.exists(save_path) and (os.path.getsize(save_path) == size):
        return True

    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    success = False
    i = 0

    while (not success) and (i < max_try):
        try:
            urllib.request.urlretrieve(url, save_path)
            success = True
        except Exception as e:
            i += 1
            logger.error(f"Error downloading {url}, retry {i}: {e}")

    return success


def gen_jar_url_path(name: str, version: str):
    group_id, artifact_id = name.split(":")
    group_path = "/".join(group_id.split("."))
    jar_name = f"{artifact_id}-{version}.jar"
    url = (
        f"https://repo1.maven.org/maven2/{group_path}"
        + f"/{artifact_id}/{version}/{jar_name}"
    )
    save_path = os.path.join(group_path, jar_name)
    return url, save_path


def polite_download(url, save_path: str):
    download(url, save_path)
    time.sleep(random.random() * 3)


def insert_many_skip_large(col: Collection, documents: list[dict]):
    error_docs = []
    try:
        col.insert_many(documents, ordered=False)
    except Exception as e:
        for doc in documents:
            try:
                col.insert_one(doc)
            except pymongo.errors.DuplicateKeyError as e:
                pass
            except Exception as e:
                error_docs.append(doc)
    return error_docs
