import tomli
import re
import argparse
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


def get_build_backend(pyproject_content: str) -> str:
    """Get the build-backend information from the pyproject.toml content.

    Args:
        pyproject_content (str): Content of the pyproject.toml file

    Returns:
        str: Returns the build-backend string
    """

    try:
        data = tomli.loads(pyproject_content)
        build_backend = data.get("build-system", {}).get("build-backend", "")
        return build_backend
    except Exception as e:
        print(f"Unable to retrieve build-backend: {str(e)}")
        return ""


def process_blob(blob_hash: str, parse_type: str):
    """Process the specified blob hash and parse either pyproject.toml based on build-backend."""

    file_content = read_blob(blob_hash)

    if file_content:
        print(f"Processing blob: {blob_hash}")

        if parse_type == "pyproject.toml":
            try:
                # Determine the build-backend from the pyproject.toml content
                build_backend = get_build_backend(file_content)

                if build_backend.startswith("poetry"):
                    print("Build backend: Poetry")
                    dependencies = parse_poetry(file_content)
                    # Output parsed dependencies with version in the desired format
                    print("All dependencies and versions:")
                    for dep in dependencies:
                        # Modify the output format here
                        package, version = dep.split(
                            " ", 1
                        )  # Split to get package and version
                        print(f"Package: {package},Version: {version}")
                elif build_backend.startswith(
                    ("setuptools", "flit", "hatch", "scikit")
                ):
                    backend = next(
                        backend
                        for backend in ("setuptools", "flit", "hatch", "scikit")
                        if build_backend.startswith(backend)
                    )
                    print(f"Build backend: {backend.capitalize()}")
                    dependencies = parse_setuptools(file_content)

                    for dep in dependencies:
                        print(f"Package: {dep['package']}, Version: {dep['version']}")

                else:
                    print(f"Unknown build backend: {build_backend}")
                    return
            except Exception as e:
                print(f"Unable to parse pyproject.toml file: {str(e)}")
        else:
            print("Invalid parse type. Please choose 'pyproject.toml'.")
    else:
        print(f"Failed to fetch content for blob {blob_hash}")


def parse_poetry(pyproject_file: str) -> list[str]:
    """Extract dependencies with specified versions from pyproject.toml file. This function handles the 'poetry' build backend.

    Args:
        file_content (str): The content of the pyproject.cfg file as a string.

    Returns:
        list[str]: A list of dependencies with package names and versions in the format "package_name version", where the version is explicitly defined.

    """

    def extract_dependencies(deps):
        """Extract dependencies with specified versions."""
        extracted_deps = []
        version_pattern = re.compile(
            r"(==|>=|<=|!=|>|<|~\=|\^)?\S+"  # Supports all comparison operators
        )
        if isinstance(deps, dict):
            for dep_name, dep_info in deps.items():
                if dep_name == "python":
                    continue
                if isinstance(dep_info, str):
                    if version_pattern.search(dep_info):
                        dep_info = dep_info.lstrip("^~")  # Remove ^ and ~ symbols
                        extracted_deps.append(f"{dep_name} {dep_info}")
                elif isinstance(dep_info, dict):
                    version_spec = dep_info.get("version")
                    if version_spec and version_pattern.search(version_spec):
                        version_spec = version_spec.lstrip(
                            "^~"
                        )  # Remove ^ and ~ symbols
                        extracted_deps.append(f"{dep_name} {version_spec}")
        elif isinstance(deps, list):
            for dep in deps:
                if version_pattern.search(dep):
                    dep = dep.lstrip("^~")  # Remove ^ and ~ symbols
                    extracted_deps.append(f"{dep} {dep}")
        return extracted_deps

    try:
        data = tomli.loads(pyproject_file)

        # Extract dependencies sections
        poetry_dependencies = (
            data.get("tool", {}).get("poetry", {}).get("dependencies", {})
        )
        poetry_dev_dependencies = (
            data.get("tool", {}).get("poetry", {}).get("dev-dependencies", {})
        )
        project_dependencies = data.get("project", {}).get("dependencies", [])

        # Extract dependencies from tool.poetry.group.*.dependencies paths
        group_dependencies = []
        poetry_tool_data = data.get("tool", {}).get("poetry", {})
        for key, value in poetry_tool_data.get("group", {}).items():
            if "dependencies" in value:
                group_dependencies.extend(
                    extract_dependencies(value.get("dependencies", {}))
                )

        # Extract normal dependencies
        direct_dependencies = extract_dependencies(poetry_dependencies)
        dev_dependencies = extract_dependencies(poetry_dev_dependencies)
        project_deps = extract_dependencies(project_dependencies)

        # Combine all dependencies
        all_dependencies = (
            direct_dependencies + dev_dependencies + project_deps + group_dependencies
        )

        return all_dependencies

    except Exception as e:
        raise ValueError(
            f"Unable to retrieve dependencies from the provided content: {str(e)}"
        )


def parse_setuptools(pyproject_file: str) -> list[dict]:
    """Parses the pyproject.toml file to extract dependencies with specified versions. This function is designed for the 'setuptools' build backend.

    Args:
        pyproject_file (str): The content of the pyproject.toml file as a string.

    Returns:
        list[dict]: A list of dictionaries containing 'package' and 'version' keys.
                    Each dictionary represents a dependency with a specified version.
    """

    def extract_dependencies(deps):
        """Extract dependencies with explicitly specified versions. Only dependencies with a clear version are extracted.

        Args:
            deps (list): A list of dependencies, which could be strings or dictionaries.

        Returns:
            list: A list of dependencies with explicit version specifications.
        """
        extracted_deps = []
        for dep in deps:
            if isinstance(dep, str):  # Ensure the dependency is a string
                # Only extract dependencies with a clear version, excluding conditional or versionless dependencies
                version_match = re.search(r"(==|>=|<=|!=|>|\<|~\=)\S+", dep)
                if version_match:
                    # If a version requirement is matched, and it's not a conditional dependency
                    if ";" not in dep:
                        extracted_deps.append(dep)
        return extracted_deps

    try:
        # Load the pyproject.toml configuration using tomli (to parse the content)
        data = tomli.loads(pyproject_file)

        # Extract dependencies section
        dependencies = data.get("project", {}).get("dependencies", [])
        optional_dependencies = data.get("project", {}).get("optional-dependencies", {})

        # Extract direct dependencies with explicit versions
        direct_dependencies = extract_dependencies(dependencies)

        # Extract optional dependencies with explicit versions
        optional_deps = []
        for extra, deps in optional_dependencies.items():
            if isinstance(deps, list):
                optional_deps.extend(extract_dependencies(deps))

        # Combine direct and optional dependencies
        all_dependencies = direct_dependencies + optional_deps

        # Parse out package names and versions
        parsed_dependencies = []
        for dep in all_dependencies:
            # Use regex to match package name and version
            match = re.match(r"([a-zA-Z0-9\-_.]+)([<>=!~]{1,2}\S+)?", dep)
            if match:
                package = match.group(1)  # Get package name
                version = match.group(2)  # Get version number

                # Only add to the result list if version is specified
                if version:
                    parsed_dependencies.append({"package": package, "version": version})

        return parsed_dependencies

    except Exception as e:
        # Catch any exceptions and raise a more descriptive error
        raise ValueError(
            f"Unable to retrieve dependencies from the provided content: {str(e)}"
        )


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
        choices=["pyproject.toml"],
        help="Type of file to parse ('pyproject.toml')",
    )

    args = parser.parse_args()

    # Process the blob hash and parse based on the specified type
    process_blob(args.blob_hash, args.parse_type)
