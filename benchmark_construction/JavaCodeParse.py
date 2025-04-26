import json
from tree_sitter import Language, Parser
import tree_sitter_java as tsjava

# 1. 编译并加载 Java 语法，使用 tree_sitter_java 库来支持对 Java 代码的解析
# 这一步创建了一个 Language 对象，用于后续解析 Java 代码的语法树
JAVA_LANGUAGE = Language(tsjava.language())
# 创建一个解析器对象
parser = Parser()
# 设置解析器的语言为 Java
parser.language = JAVA_LANGUAGE

# 2. 解析 JSON 文件，该文件包含 Java 项目的依赖信息
def load_from_json(json_file_path):
    """
    此函数用于读取 JSON 文件，解析其中的 Java 项目依赖信息。
    它会创建两个映射：一个是依赖项键（groupId:artifactId:version）到包列表的映射，
    另一个是包名到版本的映射。
    :param json_file_path: JSON 文件的路径
    :return: 两个字典，分别为依赖项键到包列表的映射和包名到版本的映射
    """
    # 以只读模式打开 JSON 文件
    with open(json_file_path, 'r') as f:
        # 加载 JSON 文件内容到 Python 字典中
        data = json.load(f)
    # 用于存储依赖项键（groupId:artifactId:version）到包列表的映射
    result_map = {}
    # 新增：记录包名到版本的映射
    package_version_map = {}
    # 遍历 JSON 数据中的每个依赖项
    for entry in data.get('dependencies', []):
        # 获取依赖项的 groupId
        group_id = entry.get('groupId')
        # 获取依赖项的 artifactId
        artifact_id = entry.get('artifactId')
        # 获取依赖项的版本号
        version = entry.get('version')
        # 生成依赖项的键
        key = f"{group_id}:{artifact_id}:{version}"
        # 获取依赖项包含的包列表
        packages = entry.get('packages', [])
        # 将依赖项键和对应的包列表存入 result_map
        result_map[key] = packages
        # 建立包名到版本的映射
        for package in packages:
            package_version_map[package] = version
    # 同时返回依赖项映射和包版本映射
    return result_map, package_version_map

# 3. 构建 Import Map，将类名映射到全限定名
def build_import_map(tree, result_map):
    """
    该函数用于处理 Java 代码中的导入声明，构建类名到全限定名的映射。
    它会提取所有导入的类名，并将其与对应的全限定名关联起来。
    :param tree: 代码的语法树
    :param result_map: 依赖项键到包列表的映射
    :return: 两个集合和映射，分别为导入的类名列表和类名到全限定名的映射
    """
    # 用于存储类名到全限定名的映射
    import_map = {}
    # 存储所有导入的类名
    class_list = []
    # 获取语法树的根节点
    root_node = tree.root_node
    # 遍历根节点的子节点
    for child in root_node.children:
        # 如果当前节点是导入声明
        if child.type == 'import_declaration':
            # 获取导入的全限定类名
            full_class_name = child.child(1).text.decode('utf-8')
            # 检查该类名是否属于任一依赖包
            starts_with_full_name = any(
                full_class_name.startswith(package) for key in result_map for package in result_map[key]
            )
            if starts_with_full_name:
                # 提取类名（去掉包名部分）
                class_name = full_class_name.split('.')[-1]
                # 将类名添加到类列表中
                class_list.append(class_name)
                # 建立类名到全限定名的映射
                import_map[class_name] = full_class_name
    # 返回类列表和导入映射
    return class_list, import_map

# 4. 遍历 AST，构建符号表并捕捉方法调用
def traverse_ast(tree, class_list, import_map, package_version_map):
    """
    此函数递归遍历语法树，构建符号表并捕捉方法调用信息。
    它会记录变量名到类型的映射、变量调用的方法信息以及 API 调用的位置信息。
    :param tree: 代码的语法树
    :param class_list: 导入的类名列表
    :param import_map: 类名到全限定名的映射
    :param package_version_map: 包名到版本的映射
    :return: 三个字典，分别为变量名到类型的映射、变量调用的方法信息和 API 调用的位置信息
    """
    # 用于存储变量名到类型的映射，即符号表
    variable_type_map = {}
    # 用于存储变量调用的方法信息
    variable_method_calls = {}
    # 用于存储 API 调用的位置信息
    api_locations = []

    # 递归遍历语法树节点的内部函数
    def traverse(node, current_method=None):
        # 如果当前节点是方法声明
        if node.type == 'method_declaration':
            # 记录当前方法节点
            current_method = node
            # 获取方法的参数列表节点
            parameter_list = node.child_by_field_name('parameters')
            if parameter_list:
                # 遍历参数列表中的每个参数
                for parameter in parameter_list.children:
                    if parameter.type == 'variable_declarator_id':
                        # 获取参数的类型
                        param_type = parameter.prev_sibling.text.decode('utf-8')
                        # 获取参数的名称
                        param_name = parameter.text.decode('utf-8')
                        if param_type in class_list:
                            # 将参数名和类型存入符号表
                            variable_type_map[param_name] = param_type
            # 递归遍历当前方法节点的子节点
            traverse_children(node, current_method)
            # 方法处理完毕，清空当前方法记录
            current_method = None
        # 如果当前节点是字段声明
        elif node.type == 'field_declaration':
            # 遍历字段声明节点的子节点
            for child in node.children:
                if child.type == 'variable_declarator':
                    # 获取字段的类型
                    var_type = node.child_by_field_name('type').text.decode('utf-8')
                    # 获取字段的名称
                    var_name = child.child_by_field_name('name').text.decode('utf-8')
                    if var_type in class_list:
                        # 将字段名和类型存入符号表
                        variable_type_map[var_name] = var_type
            # 递归遍历当前字段声明节点的子节点
            traverse_children(node, current_method)
        # 如果当前节点是局部变量声明
        elif node.type == 'local_variable_declaration':
            # 遍历局部变量声明节点的子节点
            for child in node.children:
                if child.type == 'variable_declarator':
                    # 获取局部变量的类型
                    var_type = node.child_by_field_name('type').text.decode('utf-8')
                    # 获取局部变量的名称
                    var_name = child.child_by_field_name('name').text.decode('utf-8')
                    if var_type in class_list:
                        # 将局部变量名和类型存入符号表
                        variable_type_map[var_name] = var_type
            # 递归遍历当前局部变量声明节点的子节点
            traverse_children(node, current_method)
        # 如果当前节点是方法调用
        elif node.type == 'method_invocation':
            # 获取方法调用的对象节点
            scope = node.child_by_field_name('object')
            if scope:
                if scope.type == 'identifier':
                    # 获取调用方法的变量名
                    var_name = scope.text.decode('utf-8')
                    # 从符号表中获取变量的类型
                    var_type = variable_type_map.get(var_name)
                    if var_type and var_type in class_list:
                        # 获取调用的方法名
                        method_name = node.child_by_field_name('name').text.decode('utf-8')
                        # 生成方法调用信息
                        method_info = f"{var_name}.{method_name}({format_arguments(node)})"
                        # 将方法调用信息存入 variable_method_calls
                        variable_method_calls.setdefault(var_name, []).append(method_info)
                        # 获取类的全限定名
                        full_class_name = import_map.get(var_type, var_type)
                        # 新增：获取依赖版本
                        version = get_version_for_class(full_class_name, package_version_map)
                        # 记录 API 调用位置信息
                        record_api_location(full_class_name, method_name, node, current_method, 
                                            api_locations, var_name, version)
            # 递归遍历当前方法调用节点的子节点
            traverse_children(node, current_method)
        else:
            # 递归遍历当前节点的子节点
            traverse_children(node, current_method)

    # 递归遍历节点子节点的辅助函数
    def traverse_children(node, current_method):
        for child in node.children:
            traverse(child, current_method)

    # 从语法树的根节点开始遍历
    traverse(tree.root_node)
    # 返回符号表、方法调用信息和 API 调用位置信息
    return variable_type_map, variable_method_calls, api_locations

# 5. 根据全类名获取对应的依赖版本
def get_version_for_class(full_class_name, package_version_map):
    """
    该函数根据全类名查找对应的依赖版本。
    它会遍历包版本映射，找到全类名以某个包名开头的包，并返回其版本号。
    :param full_class_name: 全类名
    :param package_version_map: 包名到版本的映射
    :return: 依赖版本号，如果找不到则返回 None
    """
    # 遍历包版本映射
    for package, version in package_version_map.items():
        if full_class_name.startswith(package):
            # 如果全类名以某个包名开头，返回该包的版本号
            return version
    # 找不到时返回 None
    return None

# 6. 记录 API 调用位置信息
def record_api_location(full_class_name, method_name, method_call_node, current_method, 
                        api_locations, caller, version):
    """
    此函数用于记录 API 调用的位置信息，包括类名、全限定名、版本、调用者、调用方法名、参数、调用位置、方法定义和方法定义位置。
    :param full_class_name: 全类名
    :param method_name: 调用的方法名
    :param method_call_node: 方法调用节点
    :param current_method: 当前方法节点
    :param api_locations: 存储 API 调用位置信息的列表
    :param caller: 调用者
    :param version: 依赖版本号
    """
    # 获取方法调用的行号
    call_location = method_call_node.start_point[0] + 1
    # 初始化方法定义的行号为 None
    method_location = None
    # 初始化方法定义的字符串为空
    method_define = ''
    if current_method:
        # 获取方法定义的行号
        method_location = current_method.start_point[0] + 1
        # 拼接方法定义的字符串
        for child in current_method.children:
            if child.type != 'block':
                method_define += child.text.decode('utf-8') + ' '
        method_define = method_define.strip()
    
    # 构建 API 调用位置信息字典
    api_location = {
        'class_name': full_class_name.split('.')[-1],
        'qualified_name': full_class_name,
        'version': version,
        'caller': caller,
        'call_name': f"{full_class_name.split('.')[-1]}.{method_name}",
        'args': [format_arguments(method_call_node)],
        'call_position': call_location,
        'method_define': method_define,
        'method_position': method_location
    }
    # 将 API 调用位置信息添加到列表中
    api_locations.append(api_location)

# 格式化方法参数
def format_arguments(node):
    """
    该函数用于格式化方法调用的参数，将参数列表转换为逗号分隔的字符串。
    :param node: 方法调用节点
    :return: 格式化后的参数列表字符串
    """
    # 获取方法调用的参数列表节点
    argument_list = node.child_by_field_name('arguments')
    if argument_list:
        # 存储参数文本的列表
        args = []
        # 遍历参数列表节点的子节点
        for arg in argument_list.children:
            if arg.type not in [',', '(']:
                # 去除参数文本的首尾空格
                arg_text = arg.text.decode('utf-8').strip()
                if arg_text != ")":
                    # 将参数文本添加到列表中
                    args.append(arg_text)
        # 用逗号连接参数文本列表
        return ', '.join(args)
    # 如果没有参数，返回空字符串
    return ''

# 主函数，程序入口
def main():
    """
    程序入口函数，设置 Java 代码文件路径和 JSON 文件路径，调用相关函数进行分析，并打印结果。
    """
    # JSON 文件的路径，包含依赖信息
    json_file_path = 'D:\\JavaParser\\ParserTest\\src\\main\\java\\edu\\ustb\\data\\dep.json'
    # Java 文件的路径，待解析的 Java 代码
    java_file_path = 'D:\\JavaParser\\ParserTest\\src\\main\\java\\edu\\ustb\\parser\\api\DependencyASTParser.java'

    # 解析 JSON 文件，获取依赖项映射和包版本映射
    result_map, package_version_map = load_from_json(json_file_path)

    with open(java_file_path, 'rb') as f:
        # 读取 Java 文件内容
        source_code = f.read()
    # 解析 Java 代码，生成语法树
    tree = parser.parse(source_code)

    # 构建 Import Map，获取类列表和导入映射
    class_list, import_map = build_import_map(tree, result_map)

    # 遍历语法树，构建符号表，捕捉方法调用，记录 API 调用位置信息
    variable_type_map, variable_method_calls, api_locations = traverse_ast(
        tree, class_list, import_map, package_version_map
    )

    # 打印提取的 API 调用信息
    print("Extracted API Calls:")
    for api_loc in api_locations:
        print(api_loc)

if __name__ == "__main__":
    main()