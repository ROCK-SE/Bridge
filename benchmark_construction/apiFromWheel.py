import os
import ast
import shutil
from zipfile import ZipFile
from typing import List, Dict, Any, Optional, Tuple
from wheel_inspect import inspect_wheel

class Entity(object):
    def __init__(self, name: str) -> None:
        super().__init__()
        self.name: str = name

    @property
    def signature(self) -> str:
        return self.name

    def __str__(self):
        return str(self._serialize())

    def __repr__(self):
        return str(self)

    def _serialize(self):
        return {"name": self.name}

    @staticmethod
    def decode(s: str) -> "Entity":
        return eval(s)

    @staticmethod
    def decode_f(path: str) -> "Entity":
        if not os.path.isfile(path):
            raise ValueError(f"{path} does not exist in file system")
        with open(path, "r") as f:
            return eval(f.read())

class Alias(Entity):
    def __init__(self, name: str, full_alias: str):
        super().__init__(name)
        self.full_alias: str = full_alias

    @property
    def signature(self) -> str:
        return super().signature + f" -> {self.full_alias}"

    def _serialize(self):
        return {"name": self.name, "full_alias": self.full_alias}

class WildcardAlias(Entity):
    def __init__(self, full_aliases: List[str]):
        super().__init__("*")
        self.full_aliases: List[str] = full_aliases

    @property
    def signature(self) -> str:
        return super().signature + f" -> {self.full_aliases}"

    def _serialize(self):
        return {"name": self.name, "full_aliases": self.full_aliases}

class _ImportMapping(object):
    def __init__(self, name: str, mapping: Dict[str, str]) -> None:
        self.name: str = name
        self.mapping: Dict[str, str] = mapping

    def resolve(self, name: str) -> str:
        parts = name.split('.')
        if parts[0] in self.mapping:
            parts[0] = self.mapping[parts[0]]
        elif self.name:
            parts = self.name.split('.') + parts
        return '.'.join(parts)

    @staticmethod
    def get(module_name: str, tree: ast.AST) -> "_ImportMapping":
        mapping: Dict[str, str] = {}
        parent = module_name.rsplit('.', 1)[0] if '.' in module_name else ''
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    mapping[n.asname or n.name] = n.name
            elif isinstance(node, ast.ImportFrom):
                level = node.level
                if level == 0:
                    base = node.module or ''
                else:
                    parts = parent.split('.')
                    if level > len(parts):
                        base = node.module or ''
                    else:
                        base = '.'.join(parts[:-level+1] + ([node.module] if node.module else []))
                for n in node.names:
                    full = f"{base}.{n.name}" if base else n.name
                    mapping[n.asname or n.name] = full
        return _ImportMapping(module_name, mapping)

def build_tree_from_wheel(wheel_path: str, api_full_name: str) -> Dict[str, Any]:
    """
    解压 wheel 并构建模块树，每个文件节点包含导入映射和代码（除 __init__.py 仅保存映射）。
    """
    if not wheel_path.endswith('.whl') or not os.path.isfile(wheel_path):
        raise ValueError(f"Wheel file does not exist or not .whl: {wheel_path}")

    extract_dir = wheel_path[:-4]
    if os.path.exists(extract_dir): shutil.rmtree(extract_dir)

    try:
        with ZipFile(wheel_path, 'r') as z:
            z.extractall(extract_dir)

        meta = inspect_wheel(wheel_path)
        tops = meta.get('dist_info', {}).get('top_level', []) or [api_full_name.split('.')[0]]
        root_name = api_full_name.split('.')[0]
        if root_name not in tops:
            raise ValueError(f"{root_name} not top-level in wheel: {tops}")

        root_path = os.path.join(extract_dir, root_name)
        if not os.path.exists(root_path):
            raise FileNotFoundError(f"Root path missing: {root_path}")

        def build_subtree(path: str, mod_name: str) -> Dict[str, Any]:
            """递归构建模块树"""
            # 创建节点
            node = {
                'name': mod_name,
                'is_file': False,
                'children': [],
                'mapping': {},
                'path': path,  # 物理路径
                'type': 'directory'
            }
            
            # 检查并处理 __init__.py
            init_path = os.path.join(path, '__init__.py')
            if os.path.isfile(init_path):
                with open(init_path, 'r', encoding='utf-8', errors='ignore') as f:
                    code = f.read()
                tree = ast.parse(code, type_comments=True)
                im = _ImportMapping.get(mod_name, tree)
                node['mapping'] = im.mapping
                node['code'] = code
                node['type'] = 'package'  # 有 __init__.py 的目录是包
            
            # 处理子项
            for item in os.listdir(path):
                item_path = os.path.join(path, item)
                
                if os.path.isdir(item_path):
                    # 处理子目录
                    child_mod_name = f"{mod_name}.{item}" if mod_name else item
                    child_node = build_subtree(item_path, child_mod_name)
                    node['children'].append(child_node)
                
                elif item.endswith('.py') and item != '__init__.py':
                    # 处理 Python 文件
                    base = item[:-3]
                    child_mod_name = f"{mod_name}.{base}" if mod_name else base
                    
                    with open(item_path, 'r', encoding='utf-8', errors='ignore') as f:
                        code = f.read()
                    
                    tree = ast.parse(code, type_comments=True)
                    im = _ImportMapping.get(child_mod_name, tree)
                    
                    child_node = {
                        'name': child_mod_name,
                        'is_file': True,
                        'mapping': im.mapping,
                        'code': code,
                        'path': item_path,
                        'type': 'module'
                    }
                    node['children'].append(child_node)
            
            return node

        return build_subtree(root_path, root_name)

    finally:
        if os.path.exists(extract_dir): shutil.rmtree(extract_dir)

def navigate_to_node(root: Dict[str, Any], path_parts: List[str]) -> Dict[str, Any]:
    """
    导航到指定路径的节点 - 修复根节点处理
    """
    if not path_parts:
        return root
    
    # 检查当前节点是否有重定向
    current = root
    part = path_parts[0]
    
    # 检查重定向映射
    if part in current.get('mapping', {}):
        redirect_path = current['mapping'][part]
        redirect_parts = redirect_path.split('.')
        # 递归处理重定向路径
        return navigate_to_node(root, redirect_parts + path_parts[1:])
    
    # 检查当前节点是否匹配
    current_name_parts = current['name'].split('.')
    if current_name_parts[-1] == part:
        # 当前节点匹配，继续处理剩余部分
        if len(path_parts) == 1:
            return current
        else:
            # 在子节点中查找剩余部分
            remaining_parts = path_parts[1:]
            for child in current.get('children', []):
                child_name_parts = child['name'].split('.')
                if child_name_parts and child_name_parts[-1] == remaining_parts[0]:
                    result = navigate_to_node(child, remaining_parts)
                    if result:
                        return result
    
    # 在子节点中查找
    for child in current.get('children', []):
        child_name_parts = child['name'].split('.')
        if child_name_parts and child_name_parts[-1] == part:
            # 找到匹配的子节点
            if len(path_parts) == 1:
                return child
            else:
                # 继续导航剩余路径
                result = navigate_to_node(child, path_parts[1:])
                if result:
                    return result
    
    # 没有找到匹配的节点
    return None

def extract_function_info(code: str, func_name: str) -> Optional[Tuple[str, str]]:
    """
    从代码中提取函数信息
    """
    try:
        mod_tree = ast.parse(code, type_comments=True)
    except Exception:
        return None
    
    for node in ast.walk(mod_tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            # 跳过 overload 和存根函数
            has_overload = any(
                (isinstance(d, ast.Name) and d.id == 'overload') or
                (isinstance(d, ast.Attribute) and d.attr == 'overload')
                for d in node.decorator_list
            )
            if has_overload:
                continue
            
            # 跳过仅包含省略号或 pass 的函数体
            body = node.body
            if len(body) == 1 and isinstance(body[0], ast.Expr) and \
                    isinstance(body[0].value, ast.Constant) and body[0].value.value is Ellipsis:
                continue
            if all(isinstance(b, ast.Pass) for b in body):
                continue
            
            # 提取函数签名和体
            start_line = node.lineno - 1
            end_line = node.end_lineno
            lines = code.splitlines()[start_line:end_line]
            
            # 找到函数签名结束的行
            signature_end = 0
            for i, line in enumerate(lines):
                if line.rstrip().endswith(':'):
                    signature_end = i + 1
                    break
            
            # 提取签名
            signature_lines = lines[:signature_end]
            # 移除结尾的冒号
            if signature_lines and signature_lines[-1].rstrip().endswith(':'):
                signature_lines[-1] = signature_lines[-1].rstrip()[:-1].rstrip()
            signature = "\n".join(signature_lines)
            
            # 提取函数体
            body_lines = lines[signature_end:]
            body = "\n".join(body_lines)
            
            return signature, body
    
    return None

def find_api_implementation(
    tree: Dict[str, Any], api_full_name: str
) -> Optional[Tuple[str, str, str]]:
    """
    使用别名导航算法查找 API 实现
    """
    # 拆分 API 全名
    parts = api_full_name.split('.')
    if len(parts) < 2:
        return None
    
    # 提取模块路径和 API 名称
    module_parts = parts[:-1]
    api_name = parts[-1]
    
    # 首先尝试直接导航
    target_node = navigate_to_node(tree, module_parts)
    if target_node:
        # 检查目标节点是否有重定向
        mapping = target_node.get('mapping', {})
        if api_name in mapping:
            redirect_path = mapping[api_name]
            print(f"发现重定向: {api_name} -> {redirect_path}")
            return find_api_implementation(tree, redirect_path)
        
        # 检查目标节点的代码
        code = target_node.get('code', '')
        if code:
            func_info = extract_function_info(code, api_name)
            if func_info:
                signature, body = func_info
                full_path = f"{target_node['name']}.{api_name}"
                return full_path, signature, body
    
    print(f"直接导航失败，开始优化遍历所有 __init__.py 映射...")
    
    def find_in_mappings(node: Dict[str, Any]) -> Optional[Tuple[str, str, str]]:
        """
        递归查找映射，找到匹配立即返回，避免完全收集所有映射
        """
        # 检查当前节点的映射
        if node.get('type') in ('package') and 'mapping' in node:
            mapping = node['mapping']
            
            # 1. 检查精确匹配
            if api_name in mapping:
                redirect_path = mapping[api_name]
                print(f"在节点 {node['name']} 发现重定向: {api_name} -> {redirect_path}")
                return find_api_implementation(tree, redirect_path)
            
            # 2. 检查部分匹配
            for key, value in mapping.items():
                if key.endswith(f".{api_name}"):
                    print(f"在节点 {node['name']} 发现部分匹配重定向: {key} -> {value}")
                    return find_api_implementation(tree, value)
        
        # 递归检查子节点
        for child in node.get('children', []):
            result = find_in_mappings(child)
            if result:
                return result
        
        return None
    
    # 开始优化查找
    result = find_in_mappings(tree)
    if result:
        return result
    
    print(f"在所有 __init__.py 映射中未找到 {api_name} 的映射")
    return None

def process_wheel(wheel_path: str, api_full_name: str):
    """
    完整处理流程，添加时间计算
    """
    start_time = time.time()
    
    # 1. 构建树结构
    build_start = time.time()
    tree = build_tree_from_wheel(wheel_path, api_full_name)
    build_end = time.time()
    
    if not tree:
        print("树构建失败")
        return
    
    print(f"树构建成功，根节点: {tree['name']}")
    print(f"树构建耗时: {build_end - build_start:.3f}秒")
    
    # 2. 查找API实现
    search_start = time.time()
    impl = find_api_implementation(tree, api_full_name)
    search_end = time.time()
    
    if impl:
        path, signature, body = impl
        print("\n=== 找到实现 ===")
        print(f"path:\n{path}")
        print(f"\nsignature:\n{signature}")
        print(f"\nbody:\n{body}")
    else:
        print("\n未找到实现")
    
    print(f"\nAPI查找耗时: {search_end - search_start:.3f}秒")
    print(f"总耗时: {time.time() - start_time:.3f}秒")

# 示例用法
if __name__ == "__main__":
    import time  # 添加时间模块
    
    wheel_path = 'D:\\PyAPI\\pybc\\wheel\\pandas-2.3.0-cp313-cp313-win_amd64.whl'
    api_name = 'pandas.read_csv'
    
    print("=== 开始处理 ===")
    process_wheel(wheel_path, api_name)
    print("=== 处理完成 ===")