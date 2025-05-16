import json
import logging
import os
import urllib.request

import requests
from bs4 import BeautifulSoup
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


def format_sexpression(s, indent_level=0, indent_size=4):
    """ChatGPT + TACIXAT"""
    output = ""
    i = 0
    # Initialize to False to avoid newline for the first token
    need_newline = False
    cdepth = []  # Track colons
    while i < len(s):
        if s[i] == "(":
            output += "\n" + " " * (indent_level * indent_size) + "("
            indent_level += 1
            need_newline = False  # Avoid newline after opening parenthesis
        elif s[i] == ":":
            indent_level += 1
            cdepth.append(indent_level)  # Store depth where we saw colon
            output += ":"
        elif s[i] == ")":
            indent_level -= 1
            if len(cdepth) > 0 and indent_level == cdepth[-1]:
                # Unindent when we return to the depth we saw the last colon
                cdepth.pop()
                indent_level -= 1
            output += ")"
            need_newline = True  # Newline needed after closing parenthesis
        elif s[i] == " ":
            output += " "
        else:
            j = i
            while j < len(s) and s[j] not in ["(", ")", " ", ":"]:
                j += 1
            # Add newline and indentation only when needed
            if need_newline:
                output += "\n" + " " * (indent_level * indent_size)
            output += s[i:j]
            i = j - 1
            need_newline = True  # Next token should start on a new line
        i += 1
    return output


def _construct_filters():
    filters = {}
    filters[6] = dict(name="font", attrs={"class": "FrameItemFont"})
    for i in range(7, 11):
        filters[i] = dict(name="ul", attrs={"title": "Packages"})
    for i in range(11, 15):
        filters[i] = {"name": "th", "attrs": {"class": "colFirst", "scope": "row"}}
    filters[15] = dict(name="th", attrs={"class": "col-first", "scope": "row"})
    for i in range(16, 25):
        filters[i] = dict(name="div", attrs={"class": "col-first"})
    return filters


def java_package_list():
    filters = _construct_filters()
    PACKAGE_INDEX1 = (
        "https://docs.oracle.com/javase/{version}/docs/api/overview-frame.html"
    )
    PACKAGE_INDEX2 = "https://docs.oracle.com/en/java/javase/{version}/docs/api/allpackages-index.html"

    def crawl_single(version: int):
        assert version in range(6, 25)
        res = []
        if version < 11:
            url = PACKAGE_INDEX1.format(version=version)
        else:
            url = PACKAGE_INDEX2.format(version=version)

        html_doc = requests.get(url).content
        soup = BeautifulSoup(html_doc, "html.parser")
        filter = filters[version]

        res = []
        if version == 6:
            for font in soup.find_all(**filter):
                if font.text != "All Classes":
                    res.append(font.text)

        elif version in range(7, 11):
            ul = soup.find(**filter)
            if url:
                for li in ul.find_all(name="li"):
                    res.append(li.text)

        elif version in range(11, 25):
            for th in soup.find_all(**filter):
                if th.text == "Package":
                    continue
                res.append(th.text)

        res = list(set(res))
        return res

    res = {}
    all_pkgs = []
    for i in range(6, 25):
        packages = crawl_single(i)
        all_pkgs.extend(packages)
        print(f"{i:<2}: {len(packages)} packages")
        res[i] = packages
    res["all"] = list(set(all_pkgs))
    with open("java_standard_packages.json", "w") as outf:
        json.dump(res, outf, indent=4)
