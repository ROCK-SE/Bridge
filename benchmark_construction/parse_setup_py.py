import ast
from collections import defaultdict
from lib2to3 import refactor

from utils import parse_reqs

KEYWORDS = ["install_requires", "extras_require"]


def py2_to_py3(code: str):
    # Create a RefactoringTool with the default set of fixers
    refactoring_tool = refactor.RefactoringTool(
        refactor.get_fixers_from_package("lib2to3.fixes")
    )

    # Refactor the code
    tree = refactoring_tool.refactor_string(code, "<string>")

    # Get the converted code as a string
    converted_code = str(tree)
    return converted_code


class SetupPyVisitor(ast.NodeVisitor):
    def __init__(self, code: str, keywords: list[str] = KEYWORDS):
        try:
            self.ast = ast.parse(code)
        except:
            try:
                code = py2_to_py3(code)
                self.ast = ast.parse(code)
            except:
                return
        self.keywords = keywords
        # Store the constant values (value) of each variable (key)
        self.variable_values = {}
        # Store the dependent variables (value) of each variable (key)
        self.depends_on = defaultdict(list)
        # mapping from import aliases to their full qualified names
        self.import_aliases = {}
        # global index counter for all list variables
        self.counter = 0

    def get_keywords_values(self) -> list[str]:
        self.visit(self.ast)
        values = []
        for kw in self.keywords:
            self.visited = []
            values.extend(self.merge("@" + kw))
        return values

    def visit_Import(self, node):
        for alias in node.names:
            if alias.asname:
                self.import_aliases[alias.asname] = alias.name
            else:
                self.import_aliases[alias.name] = alias.name

    def visit_ImportFrom(self, node):
        for alias in node.names:
            full_qualified_name = node.module + "." + alias.name
            if alias.asname:
                self.import_aliases[alias.asname] = full_qualified_name
            else:
                self.import_aliases[alias.name] = full_qualified_name

    def is_setup(self, node: ast.Call) -> bool:
        """Determine whether a function call is `setup()` or `setuptools.setup()`"""
        if isinstance(node.func, ast.Name) and self.import_aliases.get(
            node.func.id, ""
        ) in ["setuptools.setup", "distutils.core.setup"]:
            return True
        if isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name) and self.import_aliases.get(
                node.func.value.id, ""
            ) in ["setuptools", "distutils.core"]:
                if node.func.attr == "setup":
                    return True
        return False

    def resolve_assignment(self, lhs: str, rhs, subscription: str | None = None):
        # rhs is a constant, append it to variable_values
        if isinstance(rhs, ast.Constant):
            self.variable_values[lhs] = rhs.value

        # rhs is a variable, add it to the depends_on
        elif isinstance(rhs, ast.Name):
            # subscription deals with the set(**kwargs)case, the subscription is
            # "install_requires" for the `install_requires`` argument,
            # "extras_require" for the `extras_require` argument
            if subscription:
                self.depends_on[lhs].append(f"{rhs.id}.{subscription}")
            else:
                self.depends_on[lhs].append(rhs.id)

        # rhs is a list or tuple, assign each element to lhs
        elif isinstance(rhs, ast.List) or isinstance(rhs, ast.Tuple):
            for elt in rhs.elts:
                self.resolve_assignment(f"{lhs}.{self.counter}", elt)
                self.counter += 1

        # rhs is a dict
        elif isinstance(rhs, ast.Dict):
            keys = rhs.keys
            values = rhs.values
            if subscription:
                # deals with the setup(**{}) case
                for i, k in enumerate(keys):
                    if isinstance(k, ast.Constant) and k.value == subscription:
                        self.resolve_assignment(lhs, values[i])
            else:
                for k, v in zip(keys, values):
                    if isinstance(k, ast.Constant):
                        self.resolve_assignment(f"{lhs}.{k.value}", v)

        # for an expression such as `a if b else c`,
        # assign both `a` and `c` to lhs
        elif isinstance(rhs, ast.IfExp):
            self.resolve_assignment(lhs, rhs.body)
            self.resolve_assignment(lhs, rhs.orelse)

        elif isinstance(rhs, ast.BinOp):
            if isinstance(rhs.op, ast.Add):
                self.resolve_assignment(lhs, rhs.left)
                self.resolve_assignment(lhs, rhs.right)

        elif isinstance(rhs, ast.Subscript):
            if isinstance(rhs.value, ast.Name) and isinstance(rhs.slice, ast.Constant):
                self.depends_on[lhs].append(f"{rhs.value.id}.{rhs.slice.value}")

        elif (
            isinstance(rhs, ast.Call)
            and isinstance(rhs.func, ast.Name)
            and rhs.func.id == "dict"
        ):
            for kw in rhs.keywords:
                k = kw.arg
                v = kw.value
                self.resolve_assignment(f"{lhs}.{k}", v)

    def visit_Assign(self, node):
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.resolve_assignment(target.id, node.value)
            elif isinstance(target, ast.Subscript):
                if isinstance(target.value, ast.Name) and isinstance(
                    target.slice, ast.Constant
                ):
                    self.resolve_assignment(
                        f"{target.value.id}.{target.slice.value}", node.value
                    )

    def visit_Call(self, node):
        # only consider `setup()` function call
        if not self.is_setup(node):
            return

        find_keywords = []
        for keyword in node.keywords:
            # setup(install_requires=xxxx)
            if keyword.arg:
                if (keyword.arg in self.keywords) and (
                    keyword.arg not in find_keywords
                ):
                    find_keywords.append(keyword.arg)
                    self.resolve_assignment("@" + keyword.arg, keyword.value)

            else:
                # setup(**kwargs) or setup(**{})
                if isinstance(keyword.value, ast.Name) or isinstance(
                    keyword.value, ast.Dict
                ):
                    for kw in self.keywords:
                        if kw in find_keywords:
                            continue
                        self.resolve_assignment("@" + kw, keyword.value, kw)

    def merge(self, variable: str) -> list[str]:
        values = []
        for k, v in self.variable_values.items():
            if k.startswith(f"{variable}.") or k.startswith(variable):
                values.append(v)

        for k, val in self.depends_on.items():
            if k in self.visited:
                continue
            if (k == variable) or (k.startswith(f"{variable}.")):
                self.visited.append(k)
                for v in val:
                    values.extend(self.merge(v))

        return values


def parse_setup_py(code: str) -> dict[str, str]:
    """Parse setup.py to extract dependencies

    Parameters
    ----------
    code : str
        the content of a setup.py file

    Returns
    -------
    dict[str, str]
        a dict where each key is the dependency's canonicalized name and the value is the dependency's specifier
    """
    setuppy_visitor = SetupPyVisitor(code, keywords=KEYWORDS)
    reqs = setuppy_visitor.get_keywords_values()
    return parse_reqs(reqs)
