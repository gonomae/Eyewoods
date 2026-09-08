# Eyewoods

Eyewoods is an app for searching through multiple sets of subtitles to find corresponding lines.
Corresponding lines are matched using timestamps, for every matching line in one set of files, all lines with overlapping timestamps in other seets will be displayed. 

## Usage

Config files are TOML files, expected to end in `.eyewoods` by default.
They are structured as in the follwing example, all values are optional:
```toml
# Defaults to the file's directory
root_path = "./"
# If true, group sub and video files in the same folder together. 
# If false, group files together if the ## wildcard matches the same string
# Defaults to true
group_by_folder = true
# Video files need to be in the same directory as the corresponding subtitle file to be found
video_glob = "VideoFileName*Pattern.mkv"
# Don't search single directories that are purely numeric and larger than this number
max_ep = 8

[[tracks]]
name = "EN"
glob = "EnglishSubs - *.ass"

[[tracks]]
name = "JP"
glob = "JapaneseSubs - *.srt"
# Shift subtitle events by time given in seconds
time_shift = -10
```

## Development

Install dependencies with

```
uv sync
```

and run with

```
uv run eyewoods.py [config_file]
```