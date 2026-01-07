import json

import pymongo
import requests
from bs4 import BeautifulSoup
from pymongo.collection import Collection


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
    libraries = []
    for item in soup.find_all(**filter):
        libraries.append(item.find("a").text)
    return libraries


def parse_font_tag(url: str, filter: dict):
    soup = get_soup(url)
    libraries = []
    for item in soup.find_all(**filter):
        if item.text != "All Classes":
            libraries.append(item.text)
    return libraries


def parse_li_tag(url: str, filter: dict):
    soup = get_soup(url)
    libraries = []
    ul = soup.find(**filter)
    if ul:
        for li in ul.find_all(name="li"):
            libraries.append(li.text)
    return libraries


def parse_th_or_div_tag(url: str, filter: dict):
    soup = get_soup(url)

    libraries = []
    for item in soup.find_all(**filter):
        if item.text == "Package":
            continue
        libraries.append(item.text)
    return libraries


def javaee_2_6_libraries(version: int):
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


def java_library_list():
    java_libraries = {}
    for version in range(25):
        url = javase_apidocs_url(version)
        filter = javase_soup_filter(version)
        parser = javase_soup_parser(version)
        java_libraries[f"javase_{version}"] = parser(url, filter)
        print(f"javase_{version}", len(java_libraries[f"javase_{version}"]))

    for version in range(2, 9):
        url = javaee_apidocs_url(version)
        filter = javaee_soup_filter(version)
        parser = javaee_soup_parser(version)
        java_libraries[f"javaee_{version}"] = parser(url, filter)
        print(f"javaee_{version}", len(java_libraries[f"javaee_{version}"]))

    for version in [8, 9, 9.1, 10, 11]:
        url = jakarta_apidocs_url(version)
        filter = jakarta_soup_filter(version)
        parser = jakarta_soup_parser(version)
        java_libraries[f"jakarta_{version}"] = parser(url, filter)
        print(f"jakarta_{version}", len(java_libraries[f"jakarta_{version}"]))

    # https://www.oracle.com/java/technologies/javacard-downloads.html#archive
    java_libraries["java_card_2.1"] = [
        "java.lang",
        "javacard.framework",
        "javacard.security",
        "javacardx.crypto",
    ]
    java_libraries["java_card_2.1.1"] = [
        "java.lang",
        "javacard.framework",
        "javacard.security",
        "javacardx.crypto",
    ]
    java_libraries["java_card_2.2"] = [
        "java.io",
        "java.lang",
        "java.rmi",
        "javacard.framework",
        "javacard.framework.service",
        "javacard.security",
        "javacardx.crypto",
    ]
    java_libraries["java_card_2.2.1"] = [
        "java.io",
        "java.lang",
        "java.rmi",
        "javacard.framework",
        "javacard.framework.service",
        "javacard.security",
        "javacardx.crypto",
    ]
    java_libraries["java_card_2.2.2"] = [
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
    java_libraries["java_card_3.0.1_classic"] = [
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
    java_libraries["java_card_3.0.1_connected"] = [
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
    java_libraries["java_card_3.0.4_classic"] = [
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
    java_libraries["java_card_3.0.5_classic"] = [
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
    java_libraries["java_card_3.1_classic"] = [
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
    java_libraries["java_card_3.2_classic"] = [
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
    java_libraries["javafx_1.0"] = [
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
    java_libraries["javafx_2.2"] = [
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
        java_libraries[f"javafx_{version}"] = parser(url, filter)
        print(f"javafx_{version}", len(java_libraries[f"javafx_{version}"]))

    java_libraries["javame_8"] = [
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

    java_libraries["java.lang"] = list_java_lang()

    with open("java_standard_libraries.json", "w") as outf:
        json.dump(java_libraries, outf, indent=4)
