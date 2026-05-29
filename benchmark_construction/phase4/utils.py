import itertools
import json
import os

import pymongo
import tree_sitter_java as tsjava
from pymongo.collection import Collection
from tree_sitter import Language, Parser, Tree

JAVA_LANGUAGE = Language(tsjava.language())
java_parser = Parser(JAVA_LANGUAGE)

java_import_query = JAVA_LANGUAGE.query(
    """
(import_declaration
    (identifier) @import_name .)
(import_declaration
    (scoped_identifier) @import_name .)
"""
)

JAVA_STDLIB = list(
    set(
        itertools.chain.from_iterable(
            json.load(open("../phase2/java_standard_libraries.json")).values()
        )
    )
)


def gen_sources_jar_path(library: str, version: str, dest_folder: str):
    group_id, artifact_id = library.split(":")
    group_path = "/".join(group_id.split("."))
    jar_name = f"{artifact_id}-{version}-sources.jar"
    url = (
        f"https://repo1.maven.org/maven2/{group_path}"
        + f"/{artifact_id}/{version}/{jar_name}"
    )
    save_path = os.path.join(dest_folder, "java", group_path, jar_name)
    return url, save_path


def parse_imports_java(tree: Tree):
    class_mappings = {}
    for match in java_import_query.matches(tree.root_node):
        import_name = match[1]["import_name"][0].text.decode(errors="ignore")
        if any(import_name.startswith(f"{p}.") for p in JAVA_STDLIB):
            continue
        class_mappings[import_name.split(".")[-1]] = import_name
    return class_mappings


def construct_file_tree(filelist: list[str]) -> dict:
    root = {}

    def get_dir_dict(dir_name: str):
        d = root.get(dir_name)
        if d is None:
            d = root[dir_name] = [[], []]
        return d

    for f in filelist:
        if f.endswith("/"):
            continue
        f = f.strip("/")
        dirname, basename = os.path.split(f)
        if dirname == "/":
            continue
        dir_dict = get_dir_dict(dirname)
        dir_dict[1].append(basename)
        while dirname != "":
            par_name, name = os.path.split(dirname)
            par_dict = get_dir_dict(par_name)
            if name not in par_dict[0]:
                par_dict[0].append(name)
            dirname = par_name

    return root


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
