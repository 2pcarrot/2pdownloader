# 2pdownloader

2pdownloader is an efficient multi-threaded download tool that supports segmented downloads and resuming interrupted downloads.

## Features
- Accelerates downloads using multi-threading
- Supports resuming interrupted downloads
- Automatically merges downloaded file segments
- Supports proxy settings

## Usage
1. Clone the repository:
   ```bash
   git clone https://github.com/2pcarrot/2pdownloader.git
   cd 2pdownloader
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Use the `download_file` function to download files:
   ```python
   from core.core import download_file

   url = "https://example.com/file.zip"
   download_file(url, dest_folder="downloads", chunk_size_mb=20, max_workers=10)
   ```

## Future Development
1. **Create a Graphical User Interface (GUI)**  
   - Plans to provide a user-friendly GUI for 2pdownloader to make download task management more intuitive.

2. **Support Plugins**  
   - Add plugin support to allow custom extensions, such as supporting more protocols or custom download logic.

## Contribution
Contributions are welcome! Please submit a Pull Request or report issues.

## License
This project is licensed under the [MIT License](LICENSE).
