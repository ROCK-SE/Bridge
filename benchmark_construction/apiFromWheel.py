import os
import importlib
from typing import Dict, List, Optional, Tuple
from tree_sitter import Parser, Language, Node, Tree
import tree_sitter_python as tspy
from isort.stdlibs.all import stdlib
import zipfile
import tempfile
import shutil

# 判断是否api存在Wheel包中并提取path、signature、body完成

# 初始化 Tree-sitter 解析器
PYTHON_LANGUAGE = Language(tspy.language())
parser = Parser()
parser.language = PYTHON_LANGUAGE

def _get_module_members(module_name: str, cache: Dict[str, List[str]]) -> List[str]:
    if module_name in cache:
        return cache[module_name]

    try:
        module = importlib.import_module(module_name)
        if hasattr(module, '__all__'):
            members = module.__all__
        else:
            members = [name for name in dir(module) if not name.startswith('_')]
        cache[module_name] = members
        return members
    except ImportError:
        print(f"警告: 无法导入模块 {module_name}，通配符导入解析可能不完整")
        return []

def _resolve_relative_module(
    module_name: Optional[str],
    level: int,
    current_filepath: str,
    project_root: str
) -> str:
    current_path = os.path.relpath(current_filepath, project_root).replace("\\", "/")
    parts = current_path.split("/")[:-1]  # 去掉文件名
    for _ in range(level):
        if parts:
            parts.pop()
    if module_name:
        parts.extend(module_name.split("."))
    # 过滤空字符串
    parts = [p for p in parts if p]
    # 如果结果为空，说明是顶级模块
    return ".".join(parts) if parts else (module_name or "")

def extract_import_info(
    node: Node,
    current_filepath: str,
    project_root: str,
    resolve_wildcards: bool = True,
    module_members_cache: Optional[Dict[str, List[str]]] = None
) -> List[Tuple[str, str]]:
    results = []
    if module_members_cache is None:
        module_members_cache = {}

    if node.type == "import_statement":
        for child in node.named_children:
            if child.type == "dotted_name":
                full_name = child.text.decode(errors="ignore")
                name = full_name.split(".")[-1]
                results.append((name, full_name))

            elif child.type == "aliased_import":
                dotted = child.child_by_field_name("name")
                alias = child.child_by_field_name("alias")
                name = dotted.text.decode(errors="ignore")
                alias_name = alias.text.decode(errors="ignore")
                results.append((alias_name, name))

    elif node.type == "import_from_statement":
        module_node = node.child_by_field_name("module_name")
        level_node = node.child_by_field_name("relative_import")
        level = 0

        if level_node:
            # level_node.text是bytes，先decode
            level = level_node.text.decode(errors="ignore").count(".")

        # 兼容from . import x这种情况，module_node可能为空
        if level == 0 and module_node is None:
            return results

        module_name = module_node.text.decode(errors="ignore") if module_node else None

        full_module_name = (
            _resolve_relative_module(module_name, level, current_filepath, project_root)
            if level > 0 else module_name
        )

        for child in node.named_children:
            if child in (module_node, level_node):
                continue
            if child.type == "dotted_name":
                name = child.text.decode(errors="ignore")
                results.append((name, f"{full_module_name}.{name}" if full_module_name else name))
            elif child.type == "aliased_import":
                dotted = child.child_by_field_name("name")
                alias = child.child_by_field_name("alias")
                name = dotted.text.decode(errors="ignore")
                alias_name = alias.text.decode(errors="ignore")
                full_name = f"{full_module_name}.{name}" if full_module_name else name
                results.append((alias_name, full_name))
            elif child.type == "wildcard_import":
                if resolve_wildcards and full_module_name:
                    members = _get_module_members(full_module_name, module_members_cache)
                    for member in members:
                        results.append((member, f"{full_module_name}.{member}"))
                else:
                    results.append(("*", full_module_name or "*"))

    return results

def build_mapping(
    tree: Tree,
    current_filepath: str,
    project_root: str,
    resolve_wildcards: bool = True
) -> Dict[str, Dict[str, str]]:
    mapping = {}
    module_members_cache = {}

    for child in tree.root_node.children:
        if child.type in ("import_statement", "import_from_statement"):
            imports = extract_import_info(
                child,
                current_filepath=current_filepath,
                project_root=project_root,
                resolve_wildcards=resolve_wildcards,
                module_members_cache=module_members_cache
            )
            for alias, full_path in imports:
                if full_path.split(".")[0] in stdlib:
                    continue
                mapping[alias] = {
                    "type": "import",
                    "value": full_path
                }

        elif child.type == "class_definition":
            class_name_node = child.child_by_field_name("name")
            if class_name_node:
                class_name = class_name_node.text.decode(errors="ignore")
                class_content = child.text.decode(errors="ignore")
                mapping[class_name] = {
                    "type": "class_definition",
                    "value": class_content
                }

        elif child.type == "function_definition":
            func_name_node = child.child_by_field_name("name")
            if func_name_node:
                func_name = func_name_node.text.decode(errors="ignore")
                func_content = child.text.decode(errors="ignore")
                mapping[func_name] = {
                    "type": "function_definition",
                    "value": func_content
                }
        # 单独处理一下装饰器这个部分 要提取装饰器真正定义的api
        elif child.type == "decorated_definition":
            decorated_name_node = child.child_by_field_name("definition")
            if decorated_name_node:
                decorated_name = decorated_name_node.child_by_field_name("name").text.decode(errors="ignore")
                decorated_content = decorated_name_node.text.decode(errors="ignore")
                mapping[decorated_name] = {
                    "type": "function_definition",
                    "value": decorated_content
                }

    return mapping

def extract_class_methods(class_code: str, file_path: str, project_root: str, target_symbol: Optional[str] = None):
    tree = parser.parse(bytes(class_code, 'utf-8'))
    root_node = tree.root_node

    for node in root_node.children:
        if node.type == "class_definition":
            class_body = node.child_by_field_name("body")
            for child in class_body.children:
                if child.type == "function_definition":
                    name_node = child.child_by_field_name("name")
                    if name_node:
                        method_name = name_node.text.decode(errors="ignore")
                        if (target_symbol and method_name == target_symbol) or (not target_symbol and method_name == "__init__"):
                            # 找到了目标方法，提取签名和方法体
                            parameters_node = child.child_by_field_name("parameters")
                            if parameters_node:
                                end_byte = parameters_node.end_byte
                                signature = class_code.encode('utf-8')[child.start_byte:end_byte]
                            else:
                                signature = class_code.encode('utf-8')[child.start_byte:child.start_byte + 1]

                            body_node = child.child_by_field_name("body")
                            if body_node:
                                body = class_code.encode('utf-8')[body_node.start_byte:body_node.end_byte].decode('utf-8')
                            else:
                                body = ""
                            
                            relative_path = os.path.relpath(file_path, project_root).replace("\\", "/")
                            print("path:\n", relative_path)
                            print("signature:\n", signature)
                            print("body:\n", body)
                            return file_path
    return None


def find_api_definition(api: str, project_root: str) -> Optional[str]:
    parts = api.split(".")
    current_module_parts = parts[:-1]
    target_symbol = parts[-1]

    def locate_module_file(module_parts: List[str]) -> Optional[str]:
        base = os.path.join(project_root, *module_parts)
        init_path = os.path.join(base, "__init__.py")
        if os.path.exists(init_path):
            return init_path
        dir_path = base + ".py"
        if os.path.exists(dir_path):
            return dir_path
        return None

    current_path = locate_module_file(current_module_parts)
    if not current_path:
        print(f"模块 {'.'.join(current_module_parts)} 未找到")
        return None

    visited = set()
    while current_path and current_path not in visited:
        print(f"正在遍历文件: {current_path}")
        visited.add(current_path)

        with open(current_path, 'r', encoding='utf-8') as f:
            code = f.read()
        tree = parser.parse(bytes(code, 'utf-8'))
        mapping = build_mapping(tree, current_filepath=current_path, project_root=project_root)
        if target_symbol not in mapping:
            break

        entry = mapping[target_symbol]

        if entry["type"] == "function_definition":
            impl_code = entry["value"]
            extract_function_info(impl_code, current_path, project_root)
            return current_path

        elif entry["type"] == "class_definition":
            class_code = entry["value"]

            # Step 1: 构建类内部的 API 映射
            class_mapping = build_mapping(class_code, current_path, project_root)

            # Step 2: 在类内部映射中查找 target_symbol
            for item in class_mapping:
                if item["symbol"] == target_symbol:
                    print(f"在类中找到了匹配的 symbol: {target_symbol}")
                    return item

            # Step 3: 如果没找到，再尝试找 __init__ 方法
            for item in class_mapping:
                if item["symbol"] == "__init__":
                    print(f"未找到 {target_symbol}，但找到了类中的 __init__ 方法")
                    return item

            # Step 4: 都找不到则返回 None
            print(f"在类中找不到 {target_symbol} 或 __init__ 方法")
            return None


        elif entry["type"] == "import":
            imported_api = entry["value"]
            result = find_api_definition(imported_api, project_root)
            if result:
                return result
            else:
                break
        else:
            break

    print(f"未找到 {api} 的定义")
    return None


def extract_function_info(impl_code: str, file_path: str, project_root: str):
    # 计算相对于项目根目录的路径
    relative_path = os.path.relpath(file_path, project_root)
    # 替换路径分隔符为Python标准的斜杠
    relative_path = relative_path.replace("\\", "/")
    
    tree = parser.parse(bytes(impl_code, 'utf-8'))
    root_node = tree.root_node
    
    signature = b""
    body = ""
    
    for node in root_node.children:
        if node.type == 'function_definition':
            name_node = node.child_by_field_name('name')
            parameters_node = node.child_by_field_name('parameters')
            if parameters_node:
                end_byte = parameters_node.end_byte
                signature = impl_code.encode('utf-8')[node.start_byte:end_byte]
            body_node = node.child_by_field_name('body')
            if body_node:
                body = impl_code.encode('utf-8')[body_node.start_byte:body_node.end_byte].decode('utf-8')
    
    print("path:\n", relative_path)
    print('signature:\n', signature)
    print('body:\n', body)

if __name__ == "__main__":
    # 示例输入
    api_name = "pandas.merge"
    wheel_path = r"D:\\PyAPI\\pybc\\wheel\\pandas-2.3.0-cp313-cp313-win_amd64.whl"

    # 1. 解压 whl 文件
    temp_dir = tempfile.mkdtemp(prefix="whl_extract_")
    try:
        with zipfile.ZipFile(wheel_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)

        # 2. 查找 API 定义
        result = find_api_definition(api_name, project_root=temp_dir)
    finally:
        # 完成后删除临时解压目录
        shutil.rmtree(temp_dir)
