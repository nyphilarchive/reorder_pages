# Reorder Pages Script

This Python script is designed to clean up and reorder pages (of type `Page`) within digital archival folders in the NY Philharmonic's OrangeDAM (fka Cortex) system. It ensures that all child pages of selected parent folders appear in filename order. This is particularly useful when page order was not properly preserved during original uploads.

---

## Features

- Reorders pages within a folder by filename (`OriginalFileName`)
- Skips folders already in correct order
- Skips non-Page subtype items
- Caches folder/page relationships to recover if interrupted
- Supports dry-run mode for safe testing
- Automatically refreshes OAuth and cookie tokens on expiration
- Keeps logs of actions taken and processed pages/folders

---

## Usage

1. Place your `.env` file in the script directory with the following keys:

    ```env
    CORTEX_CLIENT_ID=your_client_id
    CORTEX_CLIENT_SECRET=your_client_secret
    CORTEX_USERNAME=your_username
    CORTEX_PASSWORD=your_password
    ```

2. Run the script:

    ```bash
    python reorder_pages.py
    ```

    To perform a dry run (no actual changes):

    ```python
    DRY_RUN = True  # Edit in script before running
    ```

---

## Output Files

- `reorder_log.csv`: Logs each step per page.
- `processed_pages.txt`: List of page IDs already processed.
- `processed_folders.txt`: List of folders that were fully processed.
- `already_ordered_folders.txt`: Folders that were already in correct order.
- `cached_parent_folders.json`: List of fetched folders by doc subtype.
- `parent_child_cache_*.json`: Temporary cache for folder/page state.

---

## Folder Types Processed

The script targets folders of the following `DocSubType` values:

- Concert Program
- Score
- Part
- Business Document
- Press Clippings

---

## Notes

- Reparenting is performed using the `DataTable` API to maintain filename-based manual order.
- Non-Page children (e.g., PDFs) are skipped.
- Cache files are deleted after successful processing of a folder.
