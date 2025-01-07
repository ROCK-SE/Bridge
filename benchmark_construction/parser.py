import argparse
import os
import subprocess
import xml.etree.ElementTree as ET

from packaging.requirements import Requirement
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


# Function to parse the POM file and extract package version information
def parse_pom(file_content: str):
    """Parse pom.xml and extract dependencies and versions"""
    # Save the content to a temporary file
    temp_pom_file = "temp_pom.xml"
    with open(temp_pom_file, "w", encoding="utf-8") as f:
        f.write(file_content)

    # Parse the pom.xml file
    tree = ET.parse(temp_pom_file)
    root = tree.getroot()

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

    # Remove the temporary POM file
    os.remove(temp_pom_file)
    return packages


# Function to parse requirements.txt content and extract dependencies and versions
def parse_requirements(file_content: str):
    """Extract dependencies and versions from requirements.txt content"""
    requirements = {}
    lines = file_content.splitlines()
    current_line = ""

    for line in lines:
        line = line.strip()

        # Ignore empty lines
        if not line:
            continue

        # If the line ends with a backslash, it means the current line is continued
        if line.endswith("\\"):
            current_line += line[:-1]  # Remove the backslash and continue concatenating
            continue
        else:
            # Join the current line and proceed
            current_line += line

        # Remove comments
        current_line = current_line.split("#")[0].strip()

        try:
            # Use packaging to parse the requirement and version
            req = Requirement(current_line)
            package = req.name
            version = str(req.specifier) if req.specifier else "latest"
            requirements[package] = version
        except ValueError:
            print(f"Invalid requirement format: {current_line}")  # Print invalid lines
            current_line = ""  # Skip the invalid line and continue with the next one
            continue

        # Reset current_line for the next line
        current_line = ""

    return requirements


# Function to process the blob hash and choose the type of parsing (POM or requirements.txt)
def process_blob(blob_hash: str, lookup_path: str, parse_type: str):
    """Process the specified blob hash and parse either POM or requirements.txt"""
    # Fetch the content of the blob
    file_content = get_blob_content_from_hash(blob_hash, lookup_path)

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
