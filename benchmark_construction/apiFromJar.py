import os
import sys
import argparse
import zipfile
import tempfile
from tree_sitter import Language, Parser
import tree_sitter_java as tsjava

def extract_methods_from_file(file_path, api_fullname, parser):
    # 分解全限定名: 包.类.方法
    parts = api_fullname.split('.')
    target_method = parts[-1]
    target_class = parts[-2] if len(parts) >= 2 else None

    code = open(file_path, 'r', encoding='utf-8').read()
    tree = parser.parse(bytes(code, 'utf8'))
    root = tree.root_node
    methods = []

    # 当前类名栈
    class_stack = []

    def traverse(node):
        # 进入类声明，记录类名
        if node.type == 'class_declaration':
            name_node = node.child_by_field_name('name')
            class_name = code[name_node.start_byte:name_node.end_byte] if name_node else None
            class_stack.append(class_name)
            for child in node.children:
                traverse(child)
            class_stack.pop()
            return

        # 查找方法声明
        if node.type == 'method_declaration':
            name_node = node.child_by_field_name('name')
            method_name = code[name_node.start_byte:name_node.end_byte] if name_node else None
            # 匹配类名和方法名
            if method_name == target_method and (target_class is None or (class_stack and class_stack[-1] == target_class)):
                params_node = node.child_by_field_name('parameters') or node.child_by_field_name('formal_parameters')
                body_node = node.child_by_field_name('body') or node.child_by_field_name('block')
                # 构造签名
                if params_node:
                    sig = code[node.start_byte:params_node.end_byte].strip()
                else:
                    sig = code[node.start_byte:node.end_byte].split('{')[0].strip()
                # 提取方法体内部
                if body_node:
                    body = code[body_node.start_byte+1:body_node.end_byte-1].strip()
                else:
                    body = ''
                methods.append((sig, body))
            return

        # 递归遍历
        for child in node.children:
            traverse(child)

    traverse(root)
    return methods


def main():
    parser_arg = argparse.ArgumentParser(
        description='Extract API implementations from a source JAR using tree-sitter.')
    parser_arg.add_argument('jar', help='Path to the source JAR file')
    parser_arg.add_argument('api', help='Fully qualified API name, e.g., com.pkg.Class.method')
    args = parser_arg.parse_args()

    JAVA_LANGUAGE = Language(tsjava.language())
    parser = Parser()
    parser.language = JAVA_LANGUAGE

    with tempfile.TemporaryDirectory() as tmpdir:
        with zipfile.ZipFile(args.jar, 'r') as jar_file:
            jar_file.extractall(tmpdir)

        all_methods = []
        for root_dir, dirs, files in os.walk(tmpdir):
            for f in files:
                if f.endswith('.java'):
                    path = os.path.join(root_dir, f)
                    methods = extract_methods_from_file(path, args.api, parser)
                    all_methods.extend(methods)

        if not all_methods:
            print(f'API "{args.api}" not found in JAR {args.jar}')
            sys.exit(1)

        # 只打印签名和方法体
        for sig, body in all_methods:
            print('Signature: ' + sig)
            print('Body:')
            print(body)
            print()  # 分隔

if __name__ == '__main__':
    main()
