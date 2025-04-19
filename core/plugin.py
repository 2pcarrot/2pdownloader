import os
import sys
import importlib.util

def load_module_from_file(module_name, file_path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None:
        raise ImportError(f"无法从位置 {file_path} 加载插件 {module_name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def load_all_modules_from_dir(dir_path):
    if not os.path.exists(dir_path):
        print(f"目录 {dir_path} 不存在")
        return
    
    for filename in os.listdir(dir_path):
        base_name, ext = os.path.splitext(filename)
        if ext == '.py':
            file_path = os.path.join(dir_path, filename)
            try:
                module = load_module_from_file(base_name, file_path)
                LOADED_PLUGINS[base_name] = module
                print(f"插件 {base_name} 已成功加载")
            except Exception as e:
                print(f"加载插件 {base_name} 时出错: {e}")

def load_all():
    LOADED_PLUGINS = {}
    script_dir = os.path.abspath(os.path.dirname(os.path.dirname(sys.argv[0])))
    plugins_dir = os.path.join(script_dir, 'plugins')
    load_all_modules_from_dir(plugins_dir)
    return LOADED_PLUGINS
