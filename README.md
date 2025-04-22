# 2pdownloader

2pdownloader is an efficient multi-threaded download tool that supports segmented downloads and resuming interrupted downloads.

## Features
- Accelerates downloads using multi-threading
- Supports resuming interrupted downloads
- Automatically merges downloaded file segments
- Supports proxy settings (automatic detection and manual configuration)
- Supports saving and loading download state for resumption

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
3. Use the following functions for downloading files:
   ```python
   from core import Downloader

   # Initialize a downloader instance
   downloader = Downloader(
       url="https://example.com/file.zip",
       download_dir="downloads",
       chunk_size_mb=20,  # Size of each chunk in MB
       max_workers=10,    # Maximum number of worker threads
       proxy_mode="system"  # Options: "system", "manual"
   )

   # Start the download
   downloader.download()

   # Get download progress
   n_downloaded, total_size, eta = downloader.get_pbar()
   print(f"Downloaded: {n_downloaded} / {total_size} bytes, Estimated Time Remaining: {eta} seconds")

   # Optionally, stop the download
   downloader.stop()
   ```

## Future Development
1. **Create a Graphical User Interface (GUI)**  
   - Plans to provide a user-friendly GUI for 2pdownloader to make download task management more intuitive.

2. **Support Plugins**  
   - Add plugin support to allow custom extensions, such as supporting more protocols or custom download logic.

## Contribution
Contributions are welcome! Please submit a Pull Request or report issues.

### Acknowledgment
This `README.md` was created with the assistance of **GitHub Copilot**, an AI-powered code assistant, to ensure clarity and accuracy in describing the functionality of the project.

## License
This project is licensed under the [MIT License](LICENSE).
