import logging
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser

PY_LANGUAGE = Language(tspython.language())
PY_PARSER = Parser(PY_LANGUAGE)

logger = logging.getLogger(__name__)
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
    level=logging.INFO,
)


@dataclass
class ModuleInfo:
    name: str
    path: str
    defines: dict[str, dict] = field(default_factory=dict)
    imports: dict[str, str] = field(default_factory=dict)
    star_imports: list[str] = field(default_factory=list)


def handle_import_statement(node: Node, info: ModuleInfo):
    # Handles
    #   import a         => a
    #   import a.b as c  =>
    #   import a, b as c
    for child in node.named_children:
        if child.type == "dotted_name":
            name = child.text.decode(errors="ignore")
            # use name or name.split(".")[0]?
            info.imports[name] = name
        elif child.type == "aliased_import":
            name = child.child_by_field_name("name").text.decode(errors="ignore")
            alias = child.child_by_field_name("alias").text.decode(errors="ignore")
            info.imports[alias] = name


def handle_import_from_statement(node: Node, info: ModuleInfo):
    # Handles:
    #   from x import y
    #   from x import y as z
    #   from .x import y
    #   from x import *
    module_name_node = node.child_by_field_name("module_name")
    module_name = module_name_node.text.decode(errors="ignore")

    level = 0
    while module_name and (module_name[0] == "."):
        level += 1
        module_name = module_name[1:]

    if level > 0:
        current_path_parts = info.path.split("/")
        if module_name:
            module_name = ".".join(current_path_parts[:-level] + [module_name]).replace(
                " ", ""
            )
        else:
            module_name = ".".join(current_path_parts[:-level]).replace(" ", "")

    for child in node.named_children[1:]:
        if child.type == "wildcard_import":
            info.star_imports.append(module_name)
        elif child.type == "dotted_name":
            name = child.text.decode(errors="ignore")
            info.imports[name] = f"{module_name}.{name}" if module_name else name
        elif child.type == "aliased_import":
            name = child.child_by_field_name("name").text.decode(errors="ignore")
            alias = child.child_by_field_name("alias").text.decode(errors="ignore")
            info.imports[alias] = f"{module_name}.{name}" if module_name else name


def extract_assigned_names(node: Node):
    if node is None:
        return set()

    if node.type == "identifier":
        return {node.text.decode(errors="ignore")}

    elif node.type in ["tuple_pattern", "list_pattern", "pattern_list"]:
        res = set()
        for child in node.named_children:
            res |= extract_assigned_names(child)
        return res

    return set()


def handle_assignment_statement(node: Node, info: ModuleInfo):
    left_node = node.child_by_field_name("left")
    for name in extract_assigned_names(left_node):
        info.defines[name] = {"type": "variable", "deprecation": False}


def handle_delete_statement(node: Node, info: ModuleInfo):
    del_ids = set()
    for child in node.named_children:
        if child.type == "identifier":
            del_ids.add(child.text.decode(errors="ignore"))
        elif child.type == "expression_list":
            for cc in child.named_children:
                if cc.type == "identifier":
                    del_ids.add(cc.text.decode(errors="ignore"))
    for id in del_ids:
        del_defs = []
        for d in list(info.defines):
            if (d == id) or (d.startswith(f"{id}.")):
                info.defines.pop(d, None)
        for d in list(info.imports):
            if (d == id) or (d.startswith(f"{id}.")):
                info.imports.pop(d, None)


def extract_function_info(node: Node):
    name = node.child_by_field_name("name").text.decode(errors="ignore")
    body = node.child_by_field_name("body").text.decode(errors="ignore")
    deprecation = False
    if "deprecat" in body.lower():
        deprecation = True

    return name, deprecation


def handle_function_definition(node: Node, info: ModuleInfo):
    if node.type != "function_definition":
        return

    name, deprecation = extract_function_info(node)
    info.defines[name] = {"type": "function", "deprecation": deprecation}


def extract_class_info(node: Node):
    name = node.child_by_field_name("name").text.decode(errors="ignore")
    body_node = node.child_by_field_name("body")
    deprecation = False
    if not body_node.named_children:
        return name, deprecation
    body_children = body_node.named_children[0]
    if not body_children.named_children:
        return name, deprecation
    first_body_child = body_children.named_children[0]
    if first_body_child.type == "string":
        docstring = first_body_child.text.decode(errors="ignore")
        if "deprecat" in docstring.lower():
            deprecation = True

    return name, deprecation


def handle_class_definition(node: Node, info: ModuleInfo):
    if node.type != "class_definition":
        return

    class_name, class_deprecation = extract_class_info(node)
    info.defines[class_name] = {"type": "class", "deprecation": class_deprecation}

    body_node = node.child_by_field_name("body")
    for child in body_node.named_children:
        if child.type == "function_definition":
            method_name, method_deprecation = extract_function_info(child)
            info.defines[f"{class_name}.{method_name}"] = {
                "type": "class method",
                "deprecation": class_deprecation or method_deprecation,
            }
        elif child.type == "class_definition":
            inner_class_name, inner_class_deprecation = extract_class_info(child)
            info.defines[f"{class_name}.{inner_class_name}"] = {
                "type": "inner class",
                "deprecation": class_deprecation or inner_class_deprecation,
            }
        elif child.type == "decorated_definition":
            name, typ, deprecation = extract_decorator_definition_information(child)
            t = "class method" if typ == "function" else "inner class"
            info.defines[f"{class_name}.{name}"] = {
                "type": t,
                "deprecation": class_deprecation or deprecation,
            }


def extract_decorator_definition_information(node: Node):
    if node.type != "decorated_definition":
        return

    deprecation_decorator = False
    for child in node.named_children:
        if child.type == "decorator":
            decorator = child.text.decode(errors="ignore")
            if "deprecat" in decorator.lower():
                deprecation_decorator = True
                break

    definition_node = node.child_by_field_name("definition")
    if definition_node.type == "function_definition":
        typ = "function"
        name, deprecation = extract_function_info(definition_node)
    elif definition_node.type == "class_definition":
        typ = "class"
        name, deprecation = extract_class_info(definition_node)

    return name, typ, deprecation or deprecation_decorator


def handle_decorated_definition(node: Node, info: ModuleInfo):
    if node.type != "decorated_definition":
        return

    name, typ, deprecation = extract_decorator_definition_information(node)
    info.defines[name] = {"type": typ, "deprecation": deprecation}


def extract_symbols_in_node(node: Node, info: ModuleInfo):
    if node.type == "import_statement":
        handle_import_statement(node, info)
        return

    elif node.type == "import_from_statement":
        handle_import_from_statement(node, info)
        return

    elif node.type in ["assignment", "augmented_assignment"]:
        handle_assignment_statement(node, info)
        return

    elif node.type == "delete_statement":
        handle_delete_statement(node, info)
        return

    elif node.type == "function_definition":
        handle_function_definition(node, info)
        return

    elif node.type == "class_definition":
        handle_class_definition(node, info)
        return

    elif node.type == "decorated_definition":
        handle_decorated_definition(node, info)
        return

    for child in node.named_children:
        extract_symbols_in_node(child, info)


class APIResolver:
    """Resolve an API's definition location in a Wheel file"""

    def __init__(self, wheel_path: str):
        self.wheel_path = wheel_path
        self.zf = zipfile.ZipFile(wheel_path)
        self.module_to_path: dict[str, str] = {}
        # Cache the extracted symbols for a file/module in the wheel.
        self.module_symbols_cache: dict[str, ModuleInfo] = {}

        self._index_modules()

    def close(self):
        self.zf.close()

    def _index_modules(self):
        for path in self.zf.namelist():
            if not path.endswith(".py"):
                continue

            if ".dist-info/" in path or ".data/" in path:
                continue

            p = Path(path)
            if p.name == "__init__.py":
                module_name = ".".join(p.parts[:-1])
            else:
                module_name = ".".join(p.with_suffix("").parts)

            self.module_to_path[module_name] = path

    def resolve(self, api_fqn: str):
        parts = api_fqn.split(".")
        module_name = self._longest_importable_module(parts)

        if not module_name:
            return None

        rest_parts = parts[len(module_name.split(".")) :]
        print(module_name, rest_parts)
        return self.resolve_from_module(module_name, rest_parts)

    def _longest_importable_module(self, parts: list[str]):
        best = None
        for i in range(len(parts)):
            candidate = ".".join(parts[: i + 1])
            if candidate in self.module_to_path:
                best = candidate
        return best

    def resolve_from_module(self, module_name: str, attrs: list[str]):
        # nothing to resolve from the module
        if not attrs:
            return None

        # extract all symbols defined/imported in the module
        module_info = self.extract_symbols_in_module(module_name)
        if not module_info:
            return None

        # head is defined in the module
        if attrs[0] in module_info.defines:
            print(f"{module_info.path} defines {attrs}")
            return self._resolve_definitions(module_info, attrs)

        # head is imported from another module
        if attrs[0] in module_info.imports:
            target_module = module_info.imports[attrs[0]]
            print(f"{module_info.path} imports {attrs} in from {target_module}")
            target_fqn = ".".join([target_module] + attrs[1:])
            return self.resolve(target_fqn)

        # head maybe in one of the wildcard imports.
        for star_module in module_info.star_imports:
            target_fqn = ".".join([star_module] + attrs)
            print(f"Trying wildcard import: {star_module=}, {target_fqn=}")
            target_info = self.resolve(target_fqn)
            if target_info:
                return target_info

    def _resolve_definitions(self, module_info: ModuleInfo, attrs: list[str]):
        # we can only resolve at most 2 (symbols defined within in a class)
        num_attrs = len(attrs)
        if num_attrs > 2:
            return None

        definitions = module_info.defines
        head = attrs[0]
        if not head in definitions:
            return None

        head_info = definitions[head]
        res = {
            "fqn": f"{module_info.name}.{head}",
            "filepath": module_info.path,
            "deprecation": head_info["deprecation"],
        }
        if head_info["type"] in ["function", "variable"]:
            # no symbols should be defined in a function
            if num_attrs == 2:
                return None
            return res

        elif head_info["type"] == "class":
            if num_attrs == 1:
                return res
            # class method or inner class
            else:
                res["fqn"] = f"{module_info.name}.{head}.{attrs[1]}"
                return res

    def extract_symbols_in_module(self, module_name: str):
        if module_name in self.module_symbols_cache:
            return self.module_symbols_cache[module_name]

        if module_name not in self.module_to_path:
            return None

        path = self.module_to_path[module_name]
        src = self.zf.read(path)
        tree = PY_PARSER.parse(src)
        info = ModuleInfo(module_name, path)
        extract_symbols_in_node(tree.root_node, info)
        self.module_symbols_cache[module_name] = info
        return info
