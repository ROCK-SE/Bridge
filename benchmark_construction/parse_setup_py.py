import requests
import os
import ast, re
import pandas as pd
import astunparse
import argparse
import tempfile

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


def process_blob(blob_hash: str, parse_type: str):
    # Fetch the content of the blob
    file_content = read_blob(blob_hash)
    if file_content:
        print(f"Processing blob: {blob_hash}")
        # Create a temporary file
        with tempfile.NamedTemporaryFile(
            delete=False, mode="w+", suffix=".py"
        ) as temp_file:
            temp_file.write(file_content)
            temp_filename = temp_file.name

        if parse_type == "setup.py":
            # Parse the setup.py file and output dependencies with versions
            dependencies = parse_setup_py(temp_filename)

            print("All dependencies and versions:")
            if dependencies:
                for package in dependencies:
                    print(f"  Package: {package['dep']}, Version: {package['version']}")
            else:
                print("No dependencies found.")
        else:
            print("Invalid parse type. Please choose 'setup.py'.")

        # Remove the temporary file
        os.remove(temp_filename)
    else:
        print(f"Failed to fetch content for blob {blob_hash}")


class dflow(object):
    def __init__(self, from_, to_, condition="*", status="str", extra_info="*"):
        if from_ == to_:
            self.from_ = "*"
        else:
            self.from_ = from_
        self.to_ = to_
        self.condition = condition
        self.status = status
        self.extra_info = extra_info


class DepsVisitor(ast.NodeVisitor):
    def __init__(self, file_name):
        self.file_name = file_name

        self.flag_finish = 0
        self.keywords = [
            "install_requires",
            "tests_require",
            "setup_requires",
            "extras_require",
        ]
        with open(file_name, "r", encoding="utf-8") as f:
            contents = f.read()
            for key in self.keywords:
                if key in contents:
                    break
            else:
                return None
        self.nodes = {}
        self.UnresolvedNames = []
        self.ResolvedNames = []
        self.flag_mamual = 0
        self.statements = 0
        self.flag_args = 0
        self.deps = {}
        self.dataflow = []
        self.scope_If = []

        for (
            a
        ) in (
            self.keywords
        ):  # Iterate through self.keywords and create an empty list in self.deps for each keyword
            self.deps[a] = []
            self.UnresolvedNames.append("original@" + a)
        try:
            self.process(file_name)
        except Exception as e:
            print(file_name)
            print(e)
            return

        self.merge_df()

    def merge_df(self):
        # Merge data flows and filter/update relevant information. The main task is to generate a final end_dataflow list by searching and matching dependencies
        keywords = [
            "install_requires",
            "tests_require",
            "setup_requires",
            "extras_require",
            "original",
        ]
        end_dataflow = []

        def search(
            dfs, to, c
        ):  # Used to traverse the dfs (data flow object list) and match according to the from_ and to_ relationship
            ret_df = []
            for df in dfs:
                if to == df.from_:
                    if df.status == "str":
                        # Add relevant information according to condition c
                        if c == "*":
                            ret_df.append({"df": df, "c": df.condition})
                        else:
                            ret_df.append({"df": df, "c": c + "@" + df.condition})
                    else:  # If status is not 'str', it will recursively search downstream to_ nodes
                        if c == "*":
                            ret_df += search(dfs, df.to_, df.condition)
                        else:
                            ret_df += search(dfs, df.to_, c + "@" + df.condition)
            return ret_df

        remove_dataflow = []
        for df in self.dataflow:
            if df.from_ == "*":
                pass
            else:
                remove_dataflow.append(df)

        for df in remove_dataflow:
            if df.from_ == "*":
                continue
            if df.from_ in keywords:
                if df.status == "str":
                    end_dataflow.append(df)
                elif df.status == "file":
                    end_dataflow.append(df)

                else:
                    df_s = search(
                        remove_dataflow, df.to_, df.condition
                    )  # Call the search function to find related subsequent data flows and add the matching flows to end_dataflow
                    for df_ in df_s:
                        if df_["df"].status == "str":
                            end_dataflow.append(
                                dflow(
                                    from_=df.from_,
                                    to_=df_["df"].to_,
                                    condition=df_["c"],
                                    status="str",
                                )
                            )

        self.end_dataflow = end_dataflow

    def process(self, file_name):
        self.remove_nodes = set()
        self.process_deps(file_name)

        for rm_n in self.remove_nodes:
            self.UnresolvedNames.remove(rm_n)

        if self.flag_args == 1:  # entering setup()
            for a in self.keywords:
                self.UnresolvedNames.remove("original@" + a)
        TobeRemoved = self.UnresolvedNames.copy()
        while 1:
            self.remove_nodes = set()
            self.process_deps(file_name)

            for rm_n in self.remove_nodes:
                self.UnresolvedNames.remove(rm_n)
            if len(self.UnresolvedNames) == 0 or (
                set(TobeRemoved) == set(self.UnresolvedNames)
            ):
                TobeRemoved = self.UnresolvedNames.copy()
                break
            else:
                TobeRemoved = self.UnresolvedNames.copy()

        if len(TobeRemoved) > 0:
            pass

    def process_deps(self, file_name):
        def is_python2_syntax(contents):
            # Check if there are Python 2 specific syntax elements
            if re.search(r"print\s+(?!\()", contents) or re.search(
                r"xrange\(", contents
            ):
                return True
            return False

        try:
            with open(file_name, "rt", encoding="utf-8") as f:
                contents = f.read()
        except Exception as e:
            print(f"Error reading file {file_name}: {e}")
            return

        if is_python2_syntax(contents):
            print("use 2to3.py to transfer Python2 to Python3")
            # Call an external command to convert
            conversion_command = f'python3 2to3.py -w "{file_name}"'
            try:
                os.system(conversion_command)
                with open(file_name, "rt", encoding="utf-8") as f:
                    contents = f.read()
            except Exception as e:
                print(f"Error during conversion or re-reading file: {e}")
                return

        try:
            self.visit(ast.parse(contents))
            self.flag_finish = 1
        except Exception as e:
            print(f"Error occurred during AST parsing: {e}")

    def process_resolved(self, file_name):
        with open(file_name, "rt", encoding="utf-8") as f:
            contents = f.read()
        self.visit(ast.parse(contents))

    def isfile(self, arg):
        if isinstance(arg, ast.Str):
            pass
        else:
            return False
        candidate_file = os.path.splitext(os.path.basename(arg.s))
        if candidate_file[1] in (".txt", ".in", ".pip", ".toml", ".rst"):
            return True
        return False

    def assgin(self, value, from_scope, c="*"):
        # It is used to process expressions based on different types of AST (Abstract Syntax Tree) nodes and record the dependency relationship (data flow) in self.dataflow.
        if isinstance(value, ast.Str):
            self.dataflow.append(dflow(from_=from_scope, to_=value.s, condition=c))
        elif isinstance(value, ast.Name):
            self.dataflow.append(
                dflow(from_=from_scope, to_=value.id, status="name", condition=c)
            )
            if value.id in self.ResolvedNames:
                pass

            else:
                self.UnresolvedNames.append(from_scope + "@" + value.id)
        elif isinstance(value, ast.List) or isinstance(
            value, ast.Tuple
        ):  # list or tuple
            deps_list = value.elts

            for dep in deps_list:
                if isinstance(dep, ast.Str):
                    self.dataflow.append(
                        dflow(from_=from_scope, to_=dep.s, condition=c)
                    )

                else:
                    self.assgin(dep, from_scope, c)
        elif isinstance(value, ast.Dict):
            keys = value.keys
            values = value.values
            for i in range(len(keys)):
                self.assgin(values[i], from_scope)

        elif isinstance(value, ast.Subscript):
            if isinstance(value.value, ast.Name):
                self.dataflow.append(
                    dflow(
                        from_=from_scope, to_=value.value.id, status="name", condition=c
                    )
                )
                if value.value.id in self.ResolvedNames:
                    pass
                else:
                    self.UnresolvedNames.append(from_scope + "@" + value.value.id)  #
            elif isinstance(value.value, ast.Attribute):  # A.B['sub']
                self.assgin(value.value.value, from_scope, c)
            elif isinstance(value.value, ast.Subscript):  ##A['sub1]['sub2']
                self.assgin(value.value.value, from_scope, c)

        elif isinstance(value, ast.BinOp):  #
            left_expr = value.left
            right_expr = value.right
            if isinstance(value.op, ast.Add):
                self.assgin(left_expr, from_scope)
                self.dataflow.append(
                    dflow(from_=from_scope, to_=from_scope, status="name", condition=c)
                )
                self.assgin(right_expr, from_scope)
                self.dataflow.append(
                    dflow(from_=from_scope, to_=from_scope, status="name", condition=c)
                )

        elif isinstance(value, ast.IfExp):  # if
            self.assgin(value.body, from_scope + "_if")
            self.dataflow.append(
                dflow(
                    from_=from_scope,
                    to_=from_scope + "_if",
                    status="name",
                    condition=c + "@" + astunparse.unparse(value.test).strip(),
                )
            )
            self.assgin(value.orelse, from_scope + "_orelse")
            self.dataflow.append(
                dflow(
                    from_=from_scope,
                    to_=from_scope + "_orelse",
                    status="name",
                    condition=c + "@" + "not " + astunparse.unparse(value.test).strip(),
                )
            )

        elif isinstance(value, ast.Call):
            if isinstance(value.func, ast.Name):
                if value.func.id == "dict":
                    for kw in value.keywords:
                        self.assgin(kw.value, self.scope, c)

            for arg in value.args:
                if isinstance(arg, ast.List) or isinstance(arg, ast.Tuple):
                    for arg_l in arg.elts:
                        if isinstance(arg_l, ast.Str) and self.isfile(arg):
                            self.dataflow.append(
                                dflow(
                                    from_=from_scope,
                                    to_=arg.s,
                                    status="file",
                                    condition=c,
                                )
                            )

                elif isinstance(arg, ast.Str) and self.isfile(arg):
                    self.dataflow.append(
                        dflow(from_=from_scope, to_=arg.s, status="file", condition=c)
                    )

                else:
                    self.assgin(arg, from_scope, c)

            if isinstance(value.func, ast.Name):  # read_file('a')
                self.dataflow.append(
                    dflow(
                        from_=from_scope, to_=value.func.id, status="func", condition=c
                    )
                )
                if value.func.id in self.ResolvedNames:
                    pass
                else:
                    self.UnresolvedNames.append(from_scope + "@" + value.func.id)

            elif isinstance(value.func, ast.Attribute):  # read_file('a').split()
                self.assgin(value.func.value, from_scope, c)
        else:
            pass

    def visit_Module(self, node):
        self.generic_visit(node)

    def visit_If(self, node):
        self.scope_If.append(astunparse.unparse(node.test).strip())
        for smt in node.body:
            self.visit(smt)
        self.scope_If.pop()

        self.scope_If.append("not " + astunparse.unparse(node.test).strip())
        for smt in node.orelse:
            self.visit(smt)
        self.scope_If.pop()

    def visit_FunctionDef(self, node):
        # update return value if I can
        for arg in node.args.args:
            self.visit(arg)
        for d in node.args.defaults:
            self.visit(d)
        for smt in node.decorator_list:
            self.visit(smt)
        for smt in node.body:
            self.visit(smt)

            if self.flag_finish > 0:
                if isinstance(smt, ast.Return):
                    for it in self.UnresolvedNames:
                        if it.split("@")[1] == node.name:
                            self.scope = it.split("@")[0]
                            self.assgin(smt.value, self.scope)

    def visit_Assign(self, node):
        if self.flag_finish > 0:
            if len(node.targets) == 1:
                tar = node.targets[0]
                if isinstance(tar, ast.Name):  # a = xx
                    for it in self.UnresolvedNames:
                        if it.split("@")[1] == tar.id:
                            self.scope = it.split("@")[0]
                            self.assgin(node.value, self.scope)
                            self.remove_nodes.add(it)
                            self.ResolvedNames.append(it.split("@")[1])
                if isinstance(tar, ast.Subscript):  # a['sub'] = xx
                    if isinstance(tar.value, ast.Name):  # a['sub'] = xx
                        for it in self.UnresolvedNames:
                            if it.split("@")[1] == tar.value.id:
                                self.scope = it.split("@")[0]
                                self.assgin(node.value, self.scope)
                                self.remove_nodes.add(it)
                                self.ResolvedNames.append(it.split("@")[1])
                        if isinstance(
                            tar.slice, ast.Index
                        ):  # a['install_requires'] = xx
                            if isinstance(tar.slice.value, ast.Str):
                                if tar.slice.value.s in self.keywords:
                                    self.scope = tar.slice.value.s
                                    if isinstance(node.value, ast.Dict):
                                        keys = node.value.keys
                                        values = node.value.values
                                        for i in range(len(keys)):
                                            self.assgin(
                                                values[i],
                                                self.scope,
                                                "@".join(self.scope_If),
                                            )
                                    else:
                                        self.assgin(
                                            node.value,
                                            self.scope,
                                            "@".join(self.scope_If),
                                        )

                    elif isinstance(tar.value, ast.Subscript):  ##A['sub1]['sub2'] = xx
                        if isinstance(tar.value.value, ast.Name):
                            for it in self.UnresolvedNames:
                                if it.split("@")[1] == tar.value.value.id:
                                    self.scope = it.split("@")[0]
                                    self.assgin(node.value, self.scope)
                                    self.remove_nodes.add(it)
                                    self.ResolvedNames.append(it.split("@")[1])

                if isinstance(
                    node.value, ast.Call
                ):  # setup_info = dict()  setup(**setup_info)
                    for kw in node.value.keywords:
                        if kw.arg in self.keywords:
                            self.scope = kw.arg
                            self.from_scope = kw.arg
                            kwValue = kw.value
                            if isinstance(kwValue, ast.Dict):
                                keys = kwValue.keys
                                values = kwValue.values
                                for i in range(len(keys)):
                                    self.assgin(
                                        values[i], self.scope, "@".join(self.scope_If)
                                    )
                            else:
                                self.assgin(
                                    kwValue, self.scope, "@".join(self.scope_If)
                                )

                if isinstance(
                    node.value, ast.Dict
                ):  # setup_info = {}  setup(**setup_info)
                    for i in range(len(node.value.keys)):
                        key = node.value.keys[i]
                        kw = node.value.values[i]
                        if isinstance(key, ast.Str):
                            if key.s in self.keywords:
                                self.scope = key.s
                                if isinstance(kw, ast.Dict):
                                    values = kw.values
                                    for j in range(len(values)):
                                        self.assgin(
                                            values[j],
                                            self.scope,
                                            "@".join(self.scope_If),
                                        )
                                else:
                                    self.assgin(kw, self.scope, "@".join(self.scope_If))

    def visit_Call(self, node):
        if self.flag_finish == 0:
            if isinstance(node.func, ast.Name):  # setup()
                pass
            elif isinstance(node.func, ast.Attribute):  # setuptools.setup()
                pass

            for kw in node.keywords:
                if kw.arg in self.keywords:
                    self.scope = kw.arg
                    self.from_scope = kw.arg
                    kwValue = kw.value
                    self.flag_args = 1
                    if isinstance(kwValue, ast.Dict):
                        keys = kwValue.keys
                        values = kwValue.values
                        for i in range(len(keys)):
                            self.assgin(values[i], self.scope, "@".join(self.scope_If))
                    else:
                        self.assgin(kwValue, self.scope, "@".join(self.scope_If))

        if self.flag_finish > 0:
            if isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name):  # A.append()
                    if (
                        node.func.attr == "append" or node.func.attr == "extend"
                    ):  # A.append()；A.extend()
                        for it in self.UnresolvedNames:
                            if node.func.value.id == it.split("@")[1]:
                                for arg_ in node.args:
                                    self.assgin(
                                        arg_,
                                        node.func.value.id,
                                        "@".join(self.scope_If),
                                    )

                    if node.func.attr == "update":
                        for it in self.UnresolvedNames:
                            if node.func.value.id == it.split("@")[1]:
                                for arg_ in node.args:
                                    self.assgin(
                                        arg_,
                                        node.func.value.id,
                                        "@".join(self.scope_If),
                                    )


def read_pypi_data():
    with open("pypi_packages_normal.txt", "r") as f:
        pypi_data = {x.strip() for x in f}

    return pypi_data


pypi_data = read_pypi_data()  # Return a set containing all package names


def IsPyPIlibrary(pkg, pypi_server="https://pypi.python.org/pypi/", proxy=None):
    # This function checks if the given package (pkg) is a valid PyPI package.
    if len(pkg) == 0 or pkg == ".":  # empty
        return False
    # query in local resource
    normal_pkg = re.sub(r"[_|\-]", "-", pkg.lower())
    if normal_pkg in pypi_data:
        return True
    else:
        # query by requests
        response = requests.get("{0}{1}".format(pypi_server, pkg), proxies=proxy)
        if response.status_code == 200:
            return True
        elif response.status_code >= 300:
            return False


def Splitdepversion(py_dep):
    # This function is used to parse the name and version of a dependency.
    dep_name = ""
    version = "*"
    if len(py_dep.split(";")) > 1:
        py_dep, extra_info = py_dep.split(";", 1)
    else:
        py_dep = py_dep.split(";")[0]
        extra_info = "*"
    py_dep = py_dep.split("#")[0]

    py_dep = py_dep.strip("\\").strip()

    for i, ch in enumerate(py_dep):
        if ch in (">", "<", "^", "~", "=", "!"):
            version = str(py_dep[i:])
            break
        else:
            dep_name = dep_name + ch
    #
    dep_name = dep_name.replace('"', "")
    dep_name = dep_name.replace("'", "")
    dep_name = dep_name.strip()
    dep_name = dep_name.split("[")[0]  # A[extras]==>A
    #
    # version = version.strip('=').strip()
    version = version.replace('"', "")
    version = version.replace("'", "")
    if len(dep_name) == 0:
        return [dep_name, version, extra_info]

    if version[0] in (">", "<", "^", "~", "!") or version.startswith("=="):
        return [dep_name, version, extra_info]
    else:
        return ["", "", ""]


def parse_setup_py(file_name):
    """Parse the setup.py file and extract dependencies.

    Args:
        file_name (str): The name of the setup.py file.

    Returns:
        list: A list of dictionaries containing dependency information.
    """
    alldeps = []

    a = DepsVisitor(
        file_name
    )  # Create a DepsVisitor object to visit the AST of the setup.py file
    if a.flag_finish == 0:
        pass
    else:
        tdpes = a.end_dataflow
        for key in tdpes:
            alldeps.append(
                {
                    "dep": key.to_,
                    "filepath": file_name,
                    "type": key.from_,
                    "condition": key.condition,
                    "status": key.status,
                }
            )

    final_deps = []
    for item in alldeps:
        if item["status"] != "file":
            [dep_name, version, extra_info] = Splitdepversion(item["dep"])
            if IsPyPIlibrary(dep_name) and version != "*":
                final_deps.append({"dep": dep_name, "version": version})
    if final_deps:
        return final_deps


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
        choices=["setup.py"],
        help="Type of file to parse ('setup.py')",
    )

    args = parser.parse_args()

    # Process the blob hash and parse based on the specified type
    process_blob(args.blob_hash, args.parse_type)
