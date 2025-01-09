import xml.etree.ElementTree as ET


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
                        version_var, None
                    )  # Look up the version from properties
                    
                    #If version_var is not found in properties, skip this package
                    if version is None:
                        continue
                else:
                    version = version_text

            # If version exists, add to packages
            if version is not None:
                package["name"] = package_name
                package["version"] = version
                packages.append(package)

    return packages
