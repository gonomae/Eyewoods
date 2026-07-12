# Eyewoods

Eyewoods is an app for searching through multiple sets of subtitles to find corresponding lines.

## Usage

Config files are TOML files, expected to end in `.eyewoods` by default.
They are structured as follows, all values are optional:
```toml
root_path = "./" # Defaults to the file's directory
video_glob = "VideoFileName*Pattern.mkv" # Video files need to be in the same directory as the corresponding subtitle file to be found
max_ep = 8 # Don't search single directories that are purely numeric and larger than this number

[[tracks]]
name = "EN"
glob = "EnglishSubs - *.ass"
comments_on = false # Whether to show or hide comments (both inline and line comments), defaults to true

[[tracks]]
name = "JP"
glob = "JapaneseSubs - *.srt"
time_shift = -10 # Shift subtitle events by time given in seconds
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