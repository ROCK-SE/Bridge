import xml.etree.ElementTree as ET


def parse_pom(content: str) -> dict[str, str]:
    """Parse pom.xml to extract dependencies. There are 8 place that declare dependencies in pom.xml according to the [Maven Model](https://maven.apache.org/ref/3.9.9/maven-model/maven.html):
    1. <dependencyManagement><dependencies><dependency>
    2. <dependencies><dependency>
    3. <build><pluginManagement><plugins><plugin><dependencies><dependency>
    4. <build><plugins><plugin><dependencies><dependency>
    5. <profiles><profile><build><pluginManagement><plugins><plugin><dependencies><dependency>
    6. <profiles><profile><build><plugins><plugin><dependencies><dependency>
    7. <profiles><profile><dependencyManagement><dependencies><dependency>
    8. <profiles><profile><dependencies><dependency>

    Only 1, 2, 7, 8 are relevant to the compilation, runtime, and testing of the project. Therefore, we only consider them for extrating the dependencies.

    Parameters
    ----------
    content : str
        the content of a requirements.txt file

    Returns
    -------
    dict[str, str]
        a dict where each key is the dependency's name (groupId:atrifactId) and the value is the dependency's specifier (versionId)
    """
    try:
        root = ET.fromstring(content)
        namespaces = {}
        if "}" in root.tag:
            namespaces = {"maven": root.tag.split("}")[0].strip("{")}
        ns_prefix = ""
        if namespaces:
            ns_prefix = "maven:"

        properties = {}
        for prop in root.findall(f".//{ns_prefix}properties", namespaces):
            for child in prop:
                if child.text is None:
                    continue
                # Get the tag name without the namespace prefix
                tag_name = child.tag.split("}")[-1]
                # print(f"{tag_name}: {child.text.strip()}")
                properties[tag_name] = child.text.strip()

        def resolve_properties(original: str) -> str | None:
            if "${" not in original:
                return original

            for k, v in properties.items():
                original = original.replace("${" + k + "}", v)
            # Ensure all names are substituted
            if "${" not in original:
                return original

        dependencies = {}

        def parse_dependencies(root: ET.Element) -> dict[str, str]:
            dependencies = {}
            elements = root.findall(
                f"./{ns_prefix}dependencies/{ns_prefix}dependency", namespaces
            )
            elements += root.findall(
                f"./{ns_prefix}dependencyManagement/{ns_prefix}dependencies/{ns_prefix}dependency",
                namespaces,
            )
            for dependency in elements:
                # Get groupId and artifactId
                group_id = dependency.find(f"{ns_prefix}groupId", namespaces)
                if group_id is None:
                    continue
                artifact_id = dependency.find(f"{ns_prefix}artifactId", namespaces)
                if artifact_id is None:
                    continue
                version = dependency.find(f"{ns_prefix}version", namespaces)
                if version is None:
                    continue

                group_id = resolve_properties(group_id.text.strip())
                if group_id is None:
                    continue
                artifact_id = resolve_properties(artifact_id.text.strip())
                if artifact_id is None:
                    continue
                version = resolve_properties(version.text.strip())
                if version is None:
                    continue

                name = f"{group_id}:{artifact_id}"
                dependencies[name] = version

            return dependencies

        dependencies.update(parse_dependencies(root))
        for profile in root.findall(
            f"./{ns_prefix}profiles/{ns_prefix}profile", namespaces
        ):
            dependencies.update(parse_dependencies(profile))
        return dependencies
    except Exception as e:
        return {}
