import argparse
import os
import re
import xml.etree.ElementTree as ET
from typing import Iterable

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from woc.local import WocMapsLocal

woc = WocMapsLocal()


def read_blob(sha: str) -> str | None:
    """Read a blob's content by it sha1 value

    Parameters
    ----------
    sha : str
        a sha1 hash string containing 40 hexadecimal digits

    Returns
    -------
    str | None
        the blob's content or None if an error occurs.
    """
    try:
        data = woc.show_content("blob", sha)
    except:
        data = None
    return data


def parse_pom(content: str) -> dict[str, str]:
    """Parse pom.xml to extract dependencies

    Parameters
    ----------
    content : str
        the content of a requirements.txt file

    Returns
    -------
    dict[str, str]
        a dict where each key is the dependency's name (groupId:atrifactId) and the value is the dependency's specifier (versionId)
    """
    root = ET.fromstring(content)

    # Automatically detect namespaces if present
    namespaces = {"maven": root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}

    # Extract version information from <properties>
    properties = {}
    for prop in root.findall(".//maven:properties", namespaces):
        for child in prop:
            # Get the tag name without the namespace prefix
            tag_name = child.tag.split("}")[1] if "}" in child.tag else child.tag
            properties[tag_name] = child.text.strip()

    # Extract dependencies and their versions from <dependencies>
    packages = []
    for dependency in root.findall(
        ".//maven:dependencies/maven:dependency", namespaces
    ):
        package = {}

        # Get groupId and artifactId
        group_id = dependency.find("maven:groupId", namespaces)
        artifact_id = dependency.find("maven:artifactId", namespaces)

        if group_id is not None and artifact_id is not None:
            package_name = f"{group_id.text}:{artifact_id.text}"

            # Get version and handle variable references
            version = dependency.find("maven:version", namespaces)
            if version is not None:
                version_text = version.text.strip()

                # If the version is in the form of a variable like ${mybatis.spring}, replace with actual value
                if version_text.startswith("${") and version_text.endswith("}"):
                    version_var = version_text.strip("${}")
                    version = properties.get(
                        version_var, version_text
                    )  # Look up the version from properties
                else:
                    version = version_text

            # If version exists, add to packages
            if version is not None:
                package["name"] = package_name
                package["version"] = version
                packages.append(package)

    return packages


# https://pip.pypa.io/en/stable/reference/requirements-file-format/#comments
# There are two types of comments:
# 1. lines that begins with `#` are comments, e.g., # type 1 comment
# 2. Whitespace followed by a # in a line, e.g., abc # type 2 comment
COMMENT_RE = re.compile(r"(^|\s+)#.*$")


def join_lines(lines: list[str]) -> Iterable[str]:
    """Deal with [line continuations](https://pip.pypa.io/en/stable/reference/requirements-file-format/#line-continuations). Code adapted from [pip](https://github.com/pypa/pip/blob/ffbf6f0ce61170d6437ad5ff3a90086200ba9e2a/src/pip/_internal/req/req_file.py#L481)

    Parameters
    ----------
    lines : list[str]
        a list where each element corresponds to a line in the original requirements.txt file

    Returns
    -------
    Iterable[str]
        a generator producing joined lines
    """
    new_line: list[str] = []
    for line in lines:
        if not line.endswith("\\") or COMMENT_RE.match(line):
            if COMMENT_RE.match(line):
                # this ensures comments are always matched later
                line = " " + line
            if new_line:
                new_line.append(line)
                yield "".join(new_line)
                new_line = []
            else:
                yield line
        else:
            new_line.append(line.strip("\\"))

    # last line contains \
    if new_line:
        yield "".join(new_line)


def ignore_comments(lines: Iterable[str]) -> Iterable[str]:
    """Strips comments and filter empty lines. Code adapted from [pip](https://github.com/pypa/pip/blob/ffbf6f0ce61170d6437ad5ff3a90086200ba9e2a/src/pip/_internal/req/req_file.py#L512)

    Parameters
    ----------
    lines : list[str]
        a generator of lines produced by `join_lines`

    Returns
    -------
    Iterable[str]
        a generator producing non-empty and non-comment lines
    """
    for line in lines:
        line = COMMENT_RE.sub("", line)
        line = line.strip()
        if line:
            yield line


def preprocess(content: str) -> Iterable[str]:
    lines = content.splitlines()
    lines = join_lines(lines)
    lines = ignore_comments(lines)
    return lines


def get_args(line: str) -> str:
    """Get the arguments in each requirement line. Code adapted from [pip](https://github.com/pypa/pip/blob/ffbf6f0ce61170d6437ad5ff3a90086200ba9e2a/src/pip/_internal/req/req_file.py#L436)"""
    tokens = line.split(" ")
    args = []
    for token in tokens:
        if token.startswith("-") or token.startswith("--"):
            break
        else:
            args.append(token)
    return " ".join(args)


def parse_requirements(content: str) -> dict[str, str]:
    """Parse requirements.txt to extract dependencies

    Parameters
    ----------
    content : str
        the content of a requirements.txt file

    Returns
    -------
    dict[str, str]
        a dict where each key is the dependency's canonicalized name and the value is the dependency's specifier
    """
    requirements: dict[str, str] = {}

    for line in preprocess(content):
        try:
            args = get_args(line)
            if not args:
                continue
            req = Requirement(args)
            # The existence of url suggests that this package is not from PyPI,
            # therefore we skip it.
            if req.url is not None:
                continue
            name = canonicalize_name(req.name)
            specifier = str(req.specifier) if req.specifier else ""
            requirements[name] = specifier
        except InvalidRequirement:
            continue

    return requirements


# Function to process the blob hash and choose the type of parsing (POM or requirements.txt)
def process_blob(blob_hash: str, parse_type: str):
    """Process the specified blob hash and parse either POM or requirements.txt"""
    # Fetch the content of the blob
    file_content = read_blob(blob_hash)

    if file_content:
        print(f"Processing blob: {blob_hash}")

        if parse_type == "pom":
            # Parse the POM file and output dependencies
            packages = parse_pom(file_content)

            # Output parsed results
            for package in packages:
                print(f"Package: {package['name']}, Version: {package['version']}")

        elif parse_type == "requirements":
            # Parse the requirements.txt content and output dependencies
            dependencies = parse_requirements(file_content)

            # Output parsed results
            for package, version in dependencies.items():
                print(f"Package: {package}, Version: {version}")

        else:
            print("Invalid parse type. Please choose either 'pom' or 'requirements'.")
    else:
        print(f"Failed to fetch content for blob {blob_hash}")


# Main program
if __name__ == "__main__":
    # Directly declare the lookup tool path
    lookup_path = "~/lookup"  # Replace with the actual lookup tool path

    # Command-line arguments for blob hash and parse type
    parser = argparse.ArgumentParser(
        description="Parse blob content to extract dependencies"
    )
    parser.add_argument("blob_hash", type=str, help="The blob hash to process")
    parser.add_argument(
        "parse_type",
        choices=["pom", "requirements"],
        help="Type of file to parse ('pom' or 'requirements')",
    )

    args = parser.parse_args()

    # Process the blob hash and parse based on the specified type
    process_blob(args.blob_hash, lookup_path, args.parse_type)
