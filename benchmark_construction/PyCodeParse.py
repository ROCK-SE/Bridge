import json
from tree_sitter import Language, Parser
import tree_sitter_python as tspy

# 编译并加载python语法，使用 tree_sitter_python 库提供的语言功能
PYTHON_LANGUAGE = Language(tspy.language())
parser = Parser()
parser.language = PYTHON_LANGUAGE

# 读取并解析 JSON 包及版本信息
def load_package_versions(json_file):
    """
    此函数用于读取 JSON 文件，解析其中的包及版本信息。
    它会创建一个映射，将模块名与对应的包名和版本关联起来。
    :param json_file: JSON 文件的路径
    :return: 一个字典，键为模块名，值为 (包名, 版本) 元组
    """
    with open(json_file, 'r') as f:
        data = json.load(f)
    # 创建一个映射 {模块名 -> (包名, 版本)}
    package_versions = {}
    for dep in data['dependencies']:
        for module in dep['modules']:
            package_versions[module] = (dep['package'], dep['version'])
    return package_versions

# 处理 import 语句，提取包名和别名映射，以及类名到包名的映射
def process_imports(tree):
    """
    该函数用于处理 Python 代码中的 import 语句。
    它会提取包名、别名映射、类名到包名的映射以及模块映射。
    :param tree: 代码的语法树
    :return: 四个集合和映射，分别为包名集合、别名映射、类名到包名的映射、模块映射
    """
    imports = set()  # 使用集合来存储包名
    alias_mapping = {}  # 存储别名和包名的映射关系
    class_to_package_mapping = {}  # 存储类名到包名的映射关系
    module_mapping = {}  # 新增的映射，用于处理不同 import 情况
    root_node = tree.root_node
    for child in root_node.children:
        if child.type == 'import_statement':
            package_name = child.text.decode()
            # 去除 'import ' 前缀
            package_name = package_name.replace('import ', ' ')
            if ' as ' in package_name:
                original_name, alias = package_name.split(' as ')
                original_name = original_name.strip()
                alias = alias.strip()
                imports.add(original_name)
                alias_mapping[alias] = original_name
                module_mapping[alias] = original_name
            else:
                package_name = package_name.split(',')[0].strip()
                imports.add(package_name)
                module_mapping[package_name] = package_name
        elif child.type == 'import_from_statement':
            # 获取 from ... import ... 语句的完整文本
            import_statement = child.text.decode()
            # 去掉 from 关键字
            import_statement = import_statement.replace('from ', '')
            # 分割出包名和导入的类名部分
            package_name, import_names_str = import_statement.split(' import ')
            package_name = package_name.strip()
            imports.add(package_name)

            # 处理导入的类名
            import_names = import_names_str.split(',')
            for import_name in import_names:
                import_name = import_name.strip()
                if ' as ' in import_name:
                    # 处理有别名的情况
                    class_name, alias = import_name.split(' as ')
                    class_name = class_name.strip()
                    alias = alias.strip()
                    class_to_package_mapping[class_name] = package_name
                    class_to_package_mapping[alias] = package_name
                    module_mapping[alias] = f'{package_name}.{class_name}'
                    module_mapping[class_name] = f'{package_name}.{class_name}'
                else:
                    # 处理无别名的情况
                    class_to_package_mapping[import_name] = package_name
                    module_mapping[import_name] = f'{package_name}.{import_name}'

    return imports, alias_mapping, class_to_package_mapping, module_mapping

# 递归遍历语法树，提取 API 调用信息
def extract_api_calls(node, code, api_calls, package_versions, imports, alias_mapping, class_to_package_mapping, module_mapping):
    """
    此函数递归遍历语法树，提取 API 调用信息。
    它会记录 API 调用的包名、调用者、API 名称、参数、调用位置等信息。
    :param node: 当前遍历的语法树节点
    :param code: 源代码
    :param api_calls: 存储 API 调用信息的列表
    :param package_versions: 包版本信息映射
    :param imports: 导入的包名集合
    :param alias_mapping: 别名映射
    :param class_to_package_mapping: 类名到包名的映射
    :param module_mapping: 模块映射
    """
    if node.type == 'call':
        # 提取函数调用节点
        function_node = node.child_by_field_name('function')
        if function_node:
            # 获取方法名
            method_name = code[function_node.start_byte:function_node.end_byte].decode('utf-8')

            # 处理方法名：如果方法名是类似 "tsjava.language" 的形式
            if '.' in method_name:
                # 提取模块名（例如 'tsjava'）
                module_name, class_name = method_name.split('.', 1)
                # 查找模块的完整包名
                if module_name in module_mapping:
                    # 获取完整的包名，并拼接类名
                    method_name = f'{module_mapping[module_name]}.{class_name}'
                else:
                    # 如果没有找到模块名的映射，保持原来的方法名
                    method_name = f'{module_name}.{class_name}'
            else:
                # 如果是没有点的类名调用，直接根据 module_mapping 查找
                if method_name in module_mapping:
                    method_name = module_mapping[method_name]

            # 提取调用者
            caller = None
            if function_node.type == 'attribute':
                object_node = function_node.child_by_field_name('object')
                if object_node:
                    caller = code[object_node.start_byte:object_node.end_byte].decode('utf-8')

            # 提取调用的参数
            args = []
            args_node = node.child_by_field_name('arguments')
            if args_node:
                for arg_node in args_node.children:
                    if arg_node.type not in ('(', ')', ','):
                        args.append(code[arg_node.start_byte:arg_node.end_byte].decode('utf-8'))

            # 确定调用所在的位置（行号和列号）
            call_position = (node.start_point[0] + 1)

            # 提取 API 所在的方法的位置
            method_pos = None
            parent = node.parent
            while parent:
                if parent.type == 'function_definition':
                    method_pos = (parent.start_point[0] + 1)
                    break
                parent = parent.parent

            # 获取方法定义（method_define）
            method_define = None
            parent = node.parent
            while parent:
                if parent.type == 'function_definition':
                    method_define_node = parent.child_by_field_name('name')
                    if method_define_node:
                        method_define = method_define_node.text.decode('utf-8')
                    break
                parent = parent.parent

            # 获取包的版本信息
            package = None
            if '.' in method_name:
                potential_package = method_name.split('.')[0]
                package = alias_mapping.get(potential_package, potential_package)
                if package not in imports:
                    package = None

            if package is None and caller and '.' in caller:
                potential_package = caller.split('.')[0]
                package = alias_mapping.get(potential_package, potential_package)
                if package not in imports:
                    package = None

            if package is None:
                package = class_to_package_mapping.get(method_name)

            if package is None and caller:
                if caller in class_to_package_mapping:
                    package = class_to_package_mapping[caller]

            # 获取包的版本信息
            package_version = 'Unknown'
            if package and package in package_versions:
                package_version = package_versions.get(package, 'Unknown')

            if package in package_versions:
                package_version = package_versions.get(package, 'Unknown')

                # 将 API 调用信息加入到列表
                api_call_info = {
                    'package': package_version,
                    'caller': caller,
                    'api_name': method_name,
                    'args': args,
                    'call_line': call_position,
                    'method_define': method_define,
                    'method_line': method_pos
                }
                api_calls.append(api_call_info)

    # 递归遍历子节点
    for child in node.children:
        extract_api_calls(child, code, api_calls, package_versions, imports, alias_mapping, class_to_package_mapping, module_mapping)

# 主函数：解析代码并提取 API 调用
def analyze_api_calls(code, json_file, parser):
    """
    主函数，用于解析 Python 代码并提取 API 调用信息。
    它会调用其他辅助函数完成 JSON 文件解析、语法树解析、import 信息提取和 API 调用信息提取。
    :param code: 源代码
    :param json_file: JSON 文件路径
    :param parser: 语法解析器
    :return: 存储 API 调用信息的列表
    """
    # 存储 API 调用信息的列表
    api_calls = []

    # 解析JSON文件
    package_versions = load_package_versions(json_file)
    # print("Packages:", package_versions)

    # 解析 Python 代码
    tree = parser.parse(code)

    # 提取 import 信息、别名映射和类名到包名的映射
    imports, alias_mapping, class_to_package_mapping, module_mapping = process_imports(tree)
    # 只筛选 JSON 文件中的模块
    filtered_imports = set(module for module in imports if module in package_versions)

    # 提取 API 调用信息
    extract_api_calls(tree.root_node, code, api_calls, package_versions, filtered_imports, alias_mapping, class_to_package_mapping, module_mapping)

    return api_calls

def main():
    """
    程序入口函数，设置 Python 代码文件路径和 JSON 文件路径，调用 analyze_api_calls 函数进行分析，并打印结果。
    """
    python_file_path = 'D:\\tree-sitter\\parser_py\\data\\test.py'  # 你的 Python 代码文件路径
    json_file = 'D:\\tree-sitter\\parser_py\\data\\packages.json'  # 包版本信息文件

    # 读取源代码
    with open(python_file_path, 'rb') as f:
        source_code = f.read()

    api_calls = analyze_api_calls(source_code, json_file, parser)

    # 打印或处理提取到的 API 调用信息
    print("Extracted API Calls:")
    for api_call in api_calls:
        print(api_call)

# 示例：使用给定代码文件和包版本 JSON 文件进行分析
if __name__ == "__main__":
    main()