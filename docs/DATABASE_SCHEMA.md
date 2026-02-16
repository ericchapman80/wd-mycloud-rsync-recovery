# WD MyCloud Database Schema

This document describes the SQLite database schema used by WD MyCloud NAS devices to store file metadata.

## Database Location

On a mounted MyCloud drive, the database is typically located at:

```bash
/path/to/mycloud/restsdk/data/db/index.db
```

## Files Table Schema

The main `Files` table stores metadata for all files and directories:

```sql
CREATE TABLE Files(
    id TEXT NOT NULL,                    -- Unique file identifier (generated)
    parentID TEXT REFERENCES Files(id),  -- Parent directory ID (null = root)
    contentID TEXT,                      -- Content hash (files only)
    version INTEGER NOT NULL,            -- Incremented on every update
    name TEXT NOT NULL,                  -- Original filename
    birthTime INTEGER NOT NULL,          -- Birth time (ms since epoch)
    cTime INTEGER NOT NULL,              -- Creation time (ms since epoch)
    uTime INTEGER,                       -- Update time (ms since epoch, null if unchanged)
    mTime INTEGER,                       -- Modification time (ms since epoch, null if unchanged)
    size INTEGER NOT NULL DEFAULT 0,     -- File size in bytes
    mimeType TEXT NOT NULL DEFAULT '',   -- MIME type ('application/x.wd.dir' for directories)
    storageID TEXT NOT NULL,             -- Storage identifier
    hidden INTEGER NOT NULL DEFAULT 1,   -- Hidden flag (1=unhidden, 2=mac, 3=linux, 4=windows)
    previewSourceContentID TEXT,         -- Preview image content ID
    
    autoID INTEGER PRIMARY KEY,          -- Auto-increment ID (for FTS)
    
    -- Image metadata
    imageDate INTEGER,                   -- Image date (ms since epoch)
    imageWidth INTEGER NOT NULL DEFAULT 0,
    imageHeight INTEGER NOT NULL DEFAULT 0,
    imagePreviewWidth INTEGER NOT NULL DEFAULT 0,
    imagePreviewHeight INTEGER NOT NULL DEFAULT 0,
    imageCameraMake TEXT NOT NULL DEFAULT '',
    imageCameraModel TEXT NOT NULL DEFAULT '',
    imageAperture REAL NOT NULL DEFAULT 0,      -- f-number
    imageExposureTime REAL NOT NULL DEFAULT 0,  -- seconds
    imageISOSpeed INTEGER NOT NULL DEFAULT 0,
    
    -- GPS metadata
    imageLatitude REAL,
    imageLongitude REAL,
    imageAltitude REAL,
    
    -- Location metadata
    imageCity TEXT,
    imageState TEXT,
    imageCountry TEXT,
    
    -- Video metadata
    videoCodec TEXT,
    videoProfile TEXT,
    videoFrameRate REAL,
    audioCodec TEXT,
    audioBitrate REAL,
    audioDuration REAL,
    videoWidth INTEGER,
    videoHeight INTEGER,
    videoBitrate REAL,
    videoDate INTEGER
);
```

## Key Fields for Recovery

The most important fields for file recovery are:

| Field | Description |
|-------|-------------|
| `id` | Unique identifier for the file/directory |
| `parentID` | Links to parent directory (builds tree structure) |
| `contentID` | Maps to actual file on disk (in `files/` directory) |
| `name` | Original filename to restore |
| `mimeType` | `application/x.wd.dir` indicates a directory |
| `mTime` / `cTime` | Timestamps to preserve |

## File Storage Structure

Files are stored with content-addressed names in subdirectories:

```text
restsdk/data/files/
├── a/
│   ├── a22236cwsmelmd4on2qs2jdf
│   └── a2227rr4frppmvcdj7vopsik
├── b/
│   └── ...
└── z/
    └── ...
```

The `contentID` field in the database maps to these files. The first character of the `contentID` determines the subdirectory.

## Useful Queries

### Count all files

```sql
SELECT COUNT(*) FROM Files WHERE mimeType != 'application/x.wd.dir';
```

### Count all directories

```sql
SELECT COUNT(*) FROM Files WHERE mimeType = 'application/x.wd.dir';
```

### Find root directories

```sql
SELECT * FROM Files WHERE parentID IS NULL OR parentID = '';
```

### Get file path components

```sql
-- Recursive CTE to build full path
WITH RECURSIVE path_cte AS (
    SELECT id, parentID, name, name as full_path
    FROM Files
    WHERE parentID IS NULL OR parentID = ''
    
    UNION ALL
    
    SELECT f.id, f.parentID, f.name, p.full_path || '/' || f.name
    FROM Files f
    JOIN path_cte p ON f.parentID = p.id
)
SELECT * FROM path_cte WHERE id = 'your-file-id';
```

## Notes

- All timestamps are in **milliseconds** since Unix epoch
- The `hidden` field uses platform-specific values
- Empty `mimeType` defaults to `application/octet-stream`
- The `contentID` is only present for files, not directories
