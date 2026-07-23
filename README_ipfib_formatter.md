# ipfib binlog Formatter

A Python script to format ipfib binlog trace files by adding spacing around route update markers and route operations for better readability.

## Features

The script automatically adds blank lines:
- **3 blank lines** after `ufib_ufdm_v4_route_update():587 ------- OUT`
- **3 blank lines** before `ufib_ufdm_v4_route_update():351 ------- IN`
- **1 blank line** before `add v4 route` entries
- **1 blank line** after `installed v4 prefix ... in hardware` entries
- **1 blank line** before `del v4 route` entries
- **1 blank line** after `deleted v4 prefix ... from hardware` entries

## Usage

```bash
python3 format_ipfib_binlog.py <input_file>
```

### Example

```bash
python3 format_ipfib_binlog.py binlog_uuid_378.txt
```

This will create a formatted output file named: `binlog_uuid_378_SPACED.txt`

## Requirements

- Python 3.6 or later
- No external dependencies (uses only standard library)

## How It Works

The script:
1. Reads the input file line by line
2. Detects pattern markers using regular expressions
3. Inserts appropriate blank lines before/after specific patterns
4. Writes the formatted output to a new file with `_SPACED` suffix
5. Shows progress for large files (every 100k lines)

## Performance

- Handles files of any size (including 1M+ line files)
- Memory efficient (processes line by line)
- Shows progress updates for files over 100,000 lines

## Output

- Original file: `<filename>.<ext>`
- Formatted file: `<filename>_SPACED.<ext>`
- Original file is never modified

## Example Transformation

**Before:**
```
3021. 2026-04-09T09:47:27.765137000+00:00: ufib_ufdm_v4_route_update():587 ------- OUT
3022. 2026-04-09T09:47:27.768681000+00:00: ufib_ufdm_v4_route_update():351 ------- IN
```

**After:**
```


3021. 2026-04-09T09:47:27.765137000+00:00: ufib_ufdm_v4_route_update():587 ------- OUT



3022. 2026-04-09T09:47:27.768681000+00:00: ufib_ufdm_v4_route_update():351 ------- IN
```

## Notes

- The script can be run from any directory
- It preserves all original content and line formatting
- Only adds blank lines, never removes or modifies existing lines
- Works with absolute or relative file paths
