import argparse
import os

from parse_pom import parse_pom
from parse_requirements import parse_requirements
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
