from configparser import ConfigParser

from utils import parse_reqs


def _parse_list(value: str, separator: str = ",") -> list[str]:
    """Parse `list-semi` or `list-comma` type of values. Code adapted from [setuptools](https://github.com/pypa/setuptools/blob/fb7f3d3cab98f2c00cbf18fe887ce73007f49e18/setuptools/config/setupcfg.py#L305).

    Parameters
    ----------
    value : str
        a string to be parsed
    separator : str, optional
        list items separator character, by default ","

    Returns
    -------
    list[str]
        a list of seperated items
    """
    if "\n" in value:
        value = value.splitlines()
    else:
        value = value.split(separator)

    return [chunk.strip() for chunk in value if chunk.strip()]


def parse_install_requires(value: str | None) -> dict[str, str]:
    # We do not consider the `file:` directive. If a `file:` directive is
    # declared, its paramter is very likely to be `requirements.txt` which our
    # requirements.txt parse will deal with.
    if value is None or value.startswith("file:"):
        return {}

    reqs = _parse_list(value, separator=";")
    return parse_reqs(reqs)


def parse_extras_require(
    extras_require_section: dict[str, str]
) -> dict[str, dict[str, str]]:
    # Here, we do not deal with interpolation as pointed in [the setup.cfg's specification](https://setuptools.pypa.io/en/latest/userguide/declarative_config.html#interpolation)
    # We find that [setuptools does not enable interpolation either](https://github.com/pypa/setuptools/blob/fb7f3d3cab98f2c00cbf18fe887ce73007f49e18/setuptools/_distutils/dist.py#L402)
    extra_dependencies = {}
    for extra_name, raw_dependencies in extras_require_section.items():
        extra_dependencies[extra_name] = parse_install_requires(raw_dependencies)
    return extra_dependencies


def parse_setup_cfg(content: str) -> dict[str, str]:
    """Parse setup.cfg to extract dependencies from the `install_requires` and `extras_require` options.
    This implementation is based on [the specification of setup.cfg](https://setuptools.pypa.io/en/latest/userguide/declarative_config.html) and [the parser implemented by setuptools](https://github.com/pypa/setuptools/blob/main/setuptools/config/setupcfg.py).

    Parameters
    ----------
    content : str
        a string representing the content of a setup.cfg file

    Returns
    -------
    dict[str, str]
        a dict with the package name as the key and the package's version constraint as the value
    """
    dependencies = {}
    try:
        parser = ConfigParser()
        parser.optionxform = str
        parser.read_string(content)
        for section in parser.sections():
            if section == "options":
                # install_requires can only in the [options] section
                install_requires = parser.get(
                    "options", "install_requires", fallback=None
                )
                if install_requires is None:
                    # According to [setuptools](https://github.com/pypa/setuptools/blob/fb7f3d3cab98f2c00cbf18fe887ce73007f49e18/setuptools/dist.py#L519), "install-requires" is also a valid options
                    install_requires = parser.get(
                        "options", "install-requires", fallback=None
                    )

                for name, constraint in parse_install_requires(
                    install_requires
                ).items():
                    # if `name` is already in dependencies, we do not assign constraint.
                    # That is, we only keep the first version constraint for each package
                    dependencies[name] = dependencies.get(name, constraint)

            # extras_require can reside in the [options.extras_require] section
            # or in the [options] section with the `file:` directive where
            # value is read from a list of files and then concatenated read.
            # We do not consider the latter case since we also process
            # requirements.txt files (if the project has one), which is often
            # the parameter of the `file:` directive.
            elif section == "options.extras_require":
                extras_require_section = {}
                options = parser.options(section)
                for opt in options:
                    if opt == "__name__":
                        continue

                    val = parser.get(section, opt)
                    extras_require_section[opt] = val

                for res in parse_extras_require(extras_require_section).values():
                    for name, constraint in res.items():
                        dependencies[name] = dependencies.get(name, constraint)

    except:
        pass

    return dependencies
