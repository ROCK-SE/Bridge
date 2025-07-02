import json
import logging
import os
import random
import time
import urllib.request

import pymongo
import requests
from bs4 import BeautifulSoup
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


def get_soup(url: str) -> BeautifulSoup:
    html_doc = requests.get(url).content
    return BeautifulSoup(html_doc, "html.parser")


def parse_lia_tag(url: str, filter: dict):
    soup = get_soup(url)
    packages = []
    for item in soup.find_all(**filter):
        packages.append(item.find("a").text)
    return packages


def parse_font_tag(url: str, filter: dict):
    soup = get_soup(url)
    packages = []
    for item in soup.find_all(**filter):
        if item.text != "All Classes":
            packages.append(item.text)
    return packages


def parse_li_tag(url: str, filter: dict):
    soup = get_soup(url)
    packages = []
    ul = soup.find(**filter)
    if ul:
        for li in ul.find_all(name="li"):
            packages.append(li.text)
    return packages


def parse_th_or_div_tag(url: str, filter: dict):
    soup = get_soup(url)

    packages = []
    for item in soup.find_all(**filter):
        if item.text == "Package":
            continue
        packages.append(item.text)
    return packages


def javaee_2_6_packages(version: int):
    assert version in range(2, 7)

    if version == 2:
        url = "https://docs.oracle.com/javaee/1.2.1/api/overview-frame.html"
    elif version in [3, 4]:
        url = f"https://docs.oracle.com/javaee/1.{version}/api/overview-frame.html"
    else:
        url = f"https://docs.oracle.com/javaee/{version}/api/overview-frame.html"

    filter = dict(name="font", attrs={"class": "FrameItemFont"})
    return parse_font_tag(url, filter)


def javase_apidocs_url(version: int) -> str:
    if version == 0:
        return "https://javaalmanac.io/jdk/1.0/api/"
    elif version == 1:
        return "https://javaalmanac.io/jdk/1.1/api/packages.html"
    elif version in [2, 3, 4]:
        return f"https://javaalmanac.io/jdk/1.{version}/api/overview-frame.html"
    elif version == 5:
        return "https://docs.oracle.com/javase/1.5.0/docs/api/overview-frame.html"
    elif version in range(6, 11):
        return f"https://docs.oracle.com/javase/{version}/docs/api/overview-frame.html"
    elif version in range(11, 25):
        return f"https://docs.oracle.com/en/java/javase/{version}/docs/api/allpackages-index.html"


def javase_soup_filter(version: int) -> dict:
    if version == 0:
        return dict(name="dt")
    elif version == 1:
        return dict(name="li")
    elif version == 2:
        return dict(name="font", attrs={"id": "FrameItemFont"})
    elif version in range(3, 7):
        return dict(name="font", attrs={"class": "FrameItemFont"})
    elif version in range(7, 11):
        return dict(name="ul", attrs={"title": "Packages"})
    elif version in range(11, 15):
        return dict(name="th", attrs={"class": "colFirst", "scope": "row"})
    elif version == 15:
        return dict(name="th", attrs={"class": "col-first", "scope": "row"})
    elif version in range(16, 25):
        return dict(name="div", attrs={"class": "col-first"})


def javase_soup_parser(version: int):
    if version in [0, 1]:
        return parse_lia_tag
    elif version in range(2, 7):
        return parse_font_tag
    elif version in range(7, 11):
        return parse_li_tag
    elif version in range(11, 25):
        return parse_th_or_div_tag


def javaee_apidocs_url(version: int) -> str:
    assert version > 1
    if version == 2:
        return "https://docs.oracle.com/javaee/1.2.1/api/overview-frame.html"
    elif version in [3, 4]:
        return f"https://docs.oracle.com/javaee/1.{version}/api/overview-frame.html"
    elif version in [5, 6]:
        return f"https://docs.oracle.com/javaee/{version}/api/overview-frame.html"
    elif version == 7:
        return "https://docs.oracle.com/javaee/7/api/overview-frame.html"
    elif version == 8:
        return "https://javaee.github.io/javaee-spec/javadocs/overview-frame.html"


def javaee_soup_filter(version: int) -> dict:
    assert version > 1
    if version in range(2, 7):
        return dict(name="font", attrs={"class": "FrameItemFont"})
    elif version in [7, 8]:
        return dict(name="ul", attrs={"title": "Packages"})


def javaee_soup_parser(version: int):
    assert version > 1
    if version in range(2, 7):
        return parse_font_tag
    elif version in [7, 8]:
        return parse_li_tag


def jakarta_apidocs_url(version: int | float) -> str:
    if version in [8, 9, 9.1]:
        return f"https://jakarta.ee/specifications/platform/{version}/apidocs/overview-frame.html"
    elif version in [10, 11]:
        return f"https://jakarta.ee/specifications/platform/{version}/apidocs/allpackages-index.html"


def jakarta_soup_filter(version: int | float) -> dict:
    if version in [8, 9, 9.1]:
        return dict(name="ul", attrs={"title": "Packages"})
    elif version == 10:
        return dict(name="th", attrs={"class": "colFirst", "scope": "row"})
    elif version == 11:
        return dict(name="div", attrs={"class": "col-first"})


def jakarta_soup_parser(version: int | float):
    if version in [8, 9, 9.1]:
        return parse_li_tag
    elif version in [10, 11]:
        return parse_th_or_div_tag


def javafx_apidocs_urls(version: int) -> str:
    return f"https://openjfx.io/javadoc/{version}/allpackages-index.html"


def javafx_soup_filter(version: int) -> dict:
    if version in range(11, 16):
        return dict(name="th", attrs={"class": "colFirst", "scope": "row"})
    elif version in range(16, 18):
        return dict(name="th", attrs={"class": "col-first", "scope": "row"})
    elif version in range(18, 25):
        return dict(name="div", attrs={"class": "col-first"})


def javafx_soup_parser(version: int):
    if version in range(11, 25):
        return parse_th_or_div_tag


def list_java_lang():
    url = "https://docs.oracle.com/en/java/javase/24/docs/api/java.base/java/lang/package-summary.html"
    soup = get_soup(url)
    class_summary_div = soup.find("div", attrs={"id": "class-summary"})
    result = []
    for div in class_summary_div.find_all(name="div", attrs={"class": "col-first"}):
        if div.text != "class":
            result.append(div.text.split("<")[0])
    return result


def java_package_list():
    java_packages = {}
    for version in range(25):
        url = javase_apidocs_url(version)
        filter = javase_soup_filter(version)
        parser = javase_soup_parser(version)
        java_packages[f"javase_{version}"] = parser(url, filter)
        print(f"javase_{version}", len(java_packages[f"javase_{version}"]))

    for version in range(2, 9):
        url = javaee_apidocs_url(version)
        filter = javaee_soup_filter(version)
        parser = javaee_soup_parser(version)
        java_packages[f"javaee_{version}"] = parser(url, filter)
        print(f"javaee_{version}", len(java_packages[f"javaee_{version}"]))

    for version in [8, 9, 9.1, 10, 11]:
        url = jakarta_apidocs_url(version)
        filter = jakarta_soup_filter(version)
        parser = jakarta_soup_parser(version)
        java_packages[f"jakarta_{version}"] = parser(url, filter)
        print(f"jakarta_{version}", len(java_packages[f"jakarta_{version}"]))

    # https://www.oracle.com/java/technologies/javacard-downloads.html#archive
    java_packages["java_card_2.1"] = [
        "java.lang",
        "javacard.framework",
        "javacard.security",
        "javacardx.crypto",
    ]
    java_packages["java_card_2.1.1"] = [
        "java.lang",
        "javacard.framework",
        "javacard.security",
        "javacardx.crypto",
    ]
    java_packages["java_card_2.2"] = [
        "java.io",
        "java.lang",
        "java.rmi",
        "javacard.framework",
        "javacard.framework.service",
        "javacard.security",
        "javacardx.crypto",
    ]
    java_packages["java_card_2.2.1"] = [
        "java.io",
        "java.lang",
        "java.rmi",
        "javacard.framework",
        "javacard.framework.service",
        "javacard.security",
        "javacardx.crypto",
    ]
    java_packages["java_card_2.2.2"] = [
        "java.io",
        "java.lang",
        "java.rmi",
        "javacard.framework",
        "javacard.framework.service",
        "javacard.security",
        "javacardx.apdu",
        "javacardx.biometry",
        "javacardx.crypto",
        "javacardx.external",
        "javacardx.framework.math",
        "javacardx.framework.tlv",
        "javacardx.framework.util",
        "javacardx.framework.util.intx",
    ]
    java_packages["java_card_3.0.1_classic"] = [
        "java.io",
        "java.lang",
        "java.rmi",
        "javacard.framework",
        "javacard.framework.service",
        "javacard.security",
        "javacardx.apdu",
        "javacardx.biometry",
        "javacardx.crypto",
        "javacardx.external",
        "javacardx.framework.math",
        "javacardx.framework.tlv",
        "javacardx.framework.util",
        "javacardx.framework.util.intx",
    ]
    java_packages["java_card_3.0.1_connected"] = [
        "java.io",
        "java.lang",
        "java.lang.annotation",
        "java.rmi",
        "java.security",
        "java.util",
        "javacard.framework",
        "javacard.framework.service",
        "javacard.security",
        "javacardx.apdu",
        "javacardx.biometry",
        "javacardx.crypto",
        "javacardx.external",
        "javacardx.facilities",
        "javacardx.framework",
        "javacardx.framework.math",
        "javacardx.framework.tlv",
        "javacardx.framework.util",
        "javacardx.framework.util.intx",
        "javacardx.io",
        "javacardx.security",
        "javacardx.servlet.http",
        "javax.microedition.io",
        "javax.microedition.pki",
        "javax.servlet",
        "javax.servlet.http",
    ]
    java_packages["java_card_3.0.4_classic"] = [
        "java.io",
        "java.lang",
        "java.rmi",
        "javacard.framework",
        "javacard.framework.service",
        "javacard.security",
        "javacardx.annotations",
        "javacardx.apdu",
        "javacardx.biometry",
        "javacardx.crypto",
        "javacardx.external",
        "javacardx.framework.math",
        "javacardx.framework.string",
        "javacardx.framework.tlv",
        "javacardx.framework.util",
        "javacardx.framework.util.intx",
    ]
    java_packages["java_card_3.0.5_classic"] = [
        "java.io",
        "java.lang",
        "java.rmi",
        "javacard.framework",
        "javacard.framework.service",
        "javacard.security",
        "javacardx.annotations",
        "javacardx.apdu",
        "javacardx.apdu.util",
        "javacardx.biometry",
        "javacardx.biometry1toN",
        "javacardx.crypto",
        "javacardx.external",
        "javacardx.framework.math",
        "javacardx.framework.string",
        "javacardx.framework.tlv",
        "javacardx.framework.util",
        "javacardx.framework.util.intx",
        "javacardx.security",
    ]
    java_packages["java_card_3.1_classic"] = [
        "java.io",
        "java.lang",
        "java.rmi",
        "javacard.framework",
        "javacard.framework.service",
        "javacard.security",
        "javacardx.annotations",
        "javacardx.apdu",
        "javacardx.apdu.util",
        "javacardx.biometry",
        "javacardx.biometry1toN",
        "javacardx.crypto",
        "javacardx.external",
        "javacardx.framework.event",
        "javacardx.framework.math",
        "javacardx.framework.nio",
        "javacardx.framework.string",
        "javacardx.framework.time",
        "javacardx.framework.tlv",
        "javacardx.framework.util",
        "javacardx.framework.util.intx",
        "javacardx.security",
        "javacardx.security.cert",
        "javacardx.security.derivation",
        "javacardx.security.util",
    ]
    java_packages["java_card_3.2_classic"] = [
        "java.io",
        "java.lang",
        "java.rmi",
        "javacard.framework",
        "javacard.framework.service",
        "javacard.security",
        "javacardx.annotations",
        "javacardx.apdu",
        "javacardx.apdu.util",
        "javacardx.biometry",
        "javacardx.biometry1toN",
        "javacardx.crypto",
        "javacardx.external",
        "javacardx.framework.event",
        "javacardx.framework.math",
        "javacardx.framework.nio",
        "javacardx.framework.string",
        "javacardx.framework.time",
        "javacardx.framework.tlv",
        "javacardx.framework.util",
        "javacardx.framework.util.intx",
        "javacardx.security",
        "javacardx.security.cert",
        "javacardx.security.derivation",
        "javacardx.security.util",
    ]
    # https://docs.oracle.com/cd/E17802_01/javafx/javafx/1/docs/api/index.html
    java_packages["javafx_1.0"] = [
        "javafx.animation",
        "javafx.animation.transition",
        "javafx.async",
        "javafx.data.pull",
        "javafx.data.xml",
        "javafx.ext.swing",
        "javafx.geometry",
        "javafx.io.http",
        "javafx.lang",
        "javafx.reflect",
        "javafx.scene",
        "javafx.scene.control",
        "javafx.scene.effect",
        "javafx.scene.effect.light",
        "javafx.scene.image",
        "javafx.scene.input",
        "javafx.scene.layout",
        "javafx.scene.media",
        "javafx.scene.paint",
        "javafx.scene.shape",
        "javafx.scene.text",
        "javafx.scene.transform",
        "javafx.stage",
        "javafx.util",
    ]
    # https://docs.oracle.com/javafx/2/api/overview-frame.html
    java_packages["javafx_2.2"] = [
        "javafx.animation",
        "javafx.application",
        "javafx.beans",
        "javafx.beans.binding",
        "javafx.beans.property",
        "javafx.beans.property.adapter",
        "javafx.beans.value",
        "javafx.collections",
        "javafx.concurrent",
        "javafx.embed.swing",
        "javafx.embed.swt",
        "javafx.event",
        "javafx.fxml",
        "javafx.geometry",
        "javafx.scene",
        "javafx.scene.canvas",
        "javafx.scene.chart",
        "javafx.scene.control",
        "javafx.scene.control.cell",
        "javafx.scene.effect",
        "javafx.scene.image",
        "javafx.scene.input",
        "javafx.scene.layout",
        "javafx.scene.media",
        "javafx.scene.paint",
        "javafx.scene.shape",
        "javafx.scene.text",
        "javafx.scene.transform",
        "javafx.scene.web",
        "javafx.stage",
        "javafx.util",
        "javafx.util.converter",
        "netscape.javascript",
    ]

    for version in range(11, 25):
        url = javafx_apidocs_urls(version)
        filter = javafx_soup_filter(version)
        parser = javafx_soup_parser(version)
        java_packages[f"javafx_{version}"] = parser(url, filter)
        print(f"javafx_{version}", len(java_packages[f"javafx_{version}"]))

    java_packages["javame_8"] = [
        "java.io",
        "java.lang",
        "java.lang.annotation",
        "java.lang.ref",
        "java.net",
        "java.nio",
        "java.nio.channels",
        "java.nio.file",
        "java.nio.file.attribute",
        "java.security",
        "java.util",
        "java.util.logging",
        "javax.microedition.cellular",
        "javax.microedition.event",
        "javax.microedition.io",
        "javax.microedition.key",
        "javax.microedition.lui",
        "javax.microedition.media",
        "javax.microedition.media.control",
        "javax.wireless.messaging",
        "javax.microedition.midlet",
        "javax.microedition.pki",
        "javax.microedition.power",
        "javax.microedition.rms",
        "javax.microedition.swm",
    ]

    java_packages["java.lang"] = list_java_lang()

    with open("java_standard_packages.json", "w") as outf:
        json.dump(java_packages, outf, indent=4)
