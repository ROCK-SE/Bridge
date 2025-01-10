import argparse
import configparser
import re

from woc.local import WocMapsLocal

woc = WocMapsLocal()


def read_blob(sha: str) -> str | None:
    """Read a blob's content by its sha1 value

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
    except Exception as e:
        data = None
        print(f"Error fetching blob content: {e}")
    return data


# Function to process the blob hash and choose the type of parsing (setup.cfg)
def process_blob(blob_hash: str, parse_type: str):
    """Process the specified blob hash and parse either setup.cfg."""

    # Fetch the content of the blob
    file_content = read_blob(blob_hash)

    if file_content:
        print(f"Processing blob: {blob_hash}")

        if parse_type == "setup.cfg":
            # Parse the setup.cfg file and output dependencies with versions
            dependencies = parse_setup_cfg(file_content)

            # Output parsed results for install_requires
            print("install_requires:")
            for package in dependencies["install_requires"]:
                print(f"  Package: {package['name']}, Version: {package['version']}")

            # Output parsed results for extras_require
            print("extras_require:")
            for extra_name, deps in dependencies["extras_require"].items():
                for package in deps:
                    print(
                        f"    Package: {package['name']}, Version: {package['version']}"
                    )
        else:
            print("Invalid parse type. Please choose 'setup.cfg'.")
    else:
        print(f"Failed to fetch content for blob {blob_hash}")


def parse_install_requires(config: configparser.ConfigParser) -> list:
    """Parse the 'install_requires' section in the setup.cfg file and extract package names and versions. Only dependencies with specified versions will be included in the result.

    Args:
        config (configparser.ConfigParser): The parsed configparser object representing the setup.cfg file.

    Returns:
        list: A list of dictionaries containing the package name and version for each valid dependency.
    """

    install_requires = []
    if "options" in config and "install_requires" in config["options"]:
        install_requires_str = config["options"]["install_requires"]
        # Parse each line in the 'install_requires' section
        for line in install_requires_str.splitlines():
            line = line.strip()
            if line:  # Skip empty lines
                match = re.match(r"([^=<>]+)([=<>!]+[\d\.]+)?", line)
                if match:
                    package_name = match.group(1)
                    version = match.group(2) if match.group(2) else None
                    if version:  # Only include dependencies with specified versions
                        install_requires.append(
                            {"name": package_name, "version": version}
                        )
    return install_requires


def parse_extras_require(config: configparser.ConfigParser) -> dict:
    """Parse the 'extras_require' section in the setup.cfg file. Extracts extras and their corresponding dependencies only if the dependencies have specified versions.

    Args:
        config (configparser.ConfigParser): The parsed configparser object representing the setup.cfg file.

    Returns:
        dict: A dictionary where keys are extra names and values are lists of dictionaries containing the package name and version for each valid dependency.
    """

    extra_dependencies = {}
    if (
        "options.extras_require" in config.sections()
    ):  # Check if the 'extras_require' section exists
        extras_require_section = config["options.extras_require"]
        for extra_name, raw_dependencies in extras_require_section.items():
            valid_dependencies = []
            for line in raw_dependencies.splitlines():
                line = line.strip()
                if line:  # Skip empty lines
                    match = re.match(r"([^=<>]+)([=<>!]+[\d\.]+)?", line)
                    if match:
                        package_name = match.group(1)
                        version = match.group(2) if match.group(2) else None
                        if version:  # Only include dependencies with specified versions
                            valid_dependencies.append(
                                {"name": package_name, "version": version}
                            )
            if (
                valid_dependencies
            ):  # If any valid_dependencies exist for this extra, add to result dictionary
                extra_dependencies[extra_name] = valid_dependencies
    return extra_dependencies


def parse_setup_cfg(file_content: str) -> dict[str, list[dict[str, str]]]:
    """Parse the setup.cfg content and extract dependencies with versions.

    Args:
        file_content (str): The content of the setup.cfg file as a string.

    Returns:
        dict[str, list[dict[str, str]]]: A dictionary with two keys:
            - 'install_requires': A list of dictionaries with package names and versions.
            - 'extras_require': A dictionary with extra names as keys and lists of package versions.
    """

    config = configparser.ConfigParser()
    config.read_string(file_content)  # Read the configuration content as a string

    dependencies = {"install_requires": [], "extras_require": {}}

    # Parse 'install_requires' and 'extras_require' sections
    dependencies["install_requires"] = parse_install_requires(config)
    dependencies["extras_require"] = parse_extras_require(config)

    return dependencies


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
        choices=["setup.cfg"],
        help="Type of file to parse ('setup.cfg')",
    )

    args = parser.parse_args()

    # Process the blob hash and parse based on the specified type
    process_blob(args.blob_hash, args.parse_type)
