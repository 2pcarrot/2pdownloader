# 2pdownloader

2pdownloader 是一个高效的多线程下载工具，支持分块下载和断点续传。

## 功能特性
- 使用多线程加速下载
- 支持断点续传
- 自动合并下载的分块文件
- 支持代理设置

## 使用方法
1. 克隆仓库：
   ```bash
   git clone https://github.com/2pcarrot/2pdownloader.git
   cd 2pdownloader
   ```
2. 安装依赖：
   ```bash
   pip install -r requirements.txt
   ```
3. 使用 `download_file` 函数下载文件：
   ```python
   from core.core import download_file

   url = "https://example.com/file.zip"
   download_file(url, dest_folder="downloads", chunk_size_mb=20, max_workers=10)
   ```

## 未来开发事项
1. **制作图形化界面 (GUI)**  
   - 计划为 2pdownloader 提供一个用户友好的图形化界面，以便更直观地管理下载任务。

2. **支持插件**  
   - 添加插件化支持，为用户提供自定义扩展功能的能力，例如支持更多的协议或自定义下载逻辑。

## 贡献
欢迎贡献代码！请提交 Pull Request 或报告问题。

## 许可证
本项目使用 [MIT 许可证](LICENSE)。
