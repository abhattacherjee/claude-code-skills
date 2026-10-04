#!/usr/bin/env bash
set -eu

# extract-design-tokens.sh — Extracts design tokens from a project's CSS, HTML and Tailwind config
# Outputs the :root CSS custom properties, the dark-mode ones, the Tailwind font families and
# the Google Fonts link, for standalone HTML mockups that match the project's real look and feel.

usage() {
  cat <<'EOF'
Usage: extract-design-tokens.sh [PROJECT_DIR] [OPTIONS]

Extracts design tokens from a frontend project for use in standalone HTML
mockups:
  - CSS custom properties (--name: value) of the top-level rules whose
    selector is exactly :root, and the dark-mode ones from the top-level dark
    rules (.dark, :root.dark, .dark:root, html.dark, [data-theme=dark],
    :root[data-theme=dark]), else from a :root inside
    @media (prefers-color-scheme: dark). @layer is see-through; rules inside
    other @media or @supports rules are skipped. Braces in comments and
    quoted strings are ignored. Read from the first of these files that has
    :root variables: src/index.css, src/styles/globals.css,
    src/app/globals.css, src/main.css, src/styles.css
  - the Google Fonts link from the first of index.html, public/index.html,
    src/index.html that has one
  - the fontFamily names from tailwind.config.js, .ts or .mjs
If no :root variables are found, a warning goes to stderr (exit stays 0).

Arguments:
  PROJECT_DIR    Path to the frontend project root (default: current directory)

Options:
  --format html  Output as an HTML <style> block (default)
  --format json  Output as JSON
  --format css   Output as raw CSS variables
  -h, --help     Show this help message

Examples:
  extract-design-tokens.sh ./frontend
  extract-design-tokens.sh ./frontend --format json
  extract-design-tokens.sh ./frontend --format html > mockup-tokens.html
EOF
  exit 0
}

FORMAT="html"
PROJECT_DIR="."

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage ;;
    --format)
      if [[ $# -lt 2 ]]; then
        echo "Error: --format needs a value (html, json or css)" >&2
        exit 2
      fi
      FORMAT="$2"
      shift 2
      ;;
    *)
      PROJECT_DIR="$1"
      shift
      ;;
  esac
done

if [[ ! -d "$PROJECT_DIR" ]]; then
  echo "Error: Directory '$PROJECT_DIR' does not exist" >&2
  exit 1
fi

# Set up front: the output code reads these when nothing is found (set -u).
CSS_VARS=""
DARK_VARS=""
CSS_FILE_FOUND=""
TAILWIND_CONFIG_FOUND=""

# --- Extract Google Fonts from index.html ---
GOOGLE_FONTS_URL=""
GOOGLE_FONTS_LINK=""
for html_file in "$PROJECT_DIR/index.html" "$PROJECT_DIR/public/index.html" "$PROJECT_DIR/src/index.html"; do
  if [[ -f "$html_file" ]]; then
    GOOGLE_FONTS_URL=$(grep -oE 'https://fonts\.googleapis\.com/css2[^"'"'"']+' "$html_file" 2>/dev/null | head -1 || true)
    if [[ -n "$GOOGLE_FONTS_URL" ]]; then
      GOOGLE_FONTS_LINK="<link href=\"$GOOGLE_FONTS_URL\" rel=\"stylesheet\">"
      break
    fi
  fi
done

# --- Extract CSS custom properties ---
# css_vars <file> <light|dark|media>: print the "--name: value" lines of one kind of block.
#   light: a rule whose selector is exactly :root.
#   dark:  a rule whose every selector is a dark one: .dark, :root.dark, .dark:root,
#          html.dark, [data-theme=dark] (quoted or not), :root[data-theme=dark] or
#          [data-theme=dark]:root.
#   media: a :root rule inside an @media rule that names prefers-color-scheme and dark.
# The rule must be at the top level. @layer (named or not) is transparent, so a rule inside
# it counts as top level. Any other wrapper (@media, @supports, a nested rule) keeps its
# rules out. Braces are counted outside comments (/* */, also over several lines) and
# outside quoted strings. A line is read when it starts with "--" and does not start
# inside a comment or a string. Every \r is removed first, so CRLF files read like LF ones.
css_vars() {
  awk -v mode="$2" '
    function trim(s) { gsub(/^[ \t]+|[ \t]+$/, "", s); return s }
    # kind of a block opened by "{" after selector text s
    function kind(s,   n, i, parts, p, alldark) {
      s = trim(s)
      if (s ~ /^@layer([ \t]|$)/) return "layer"
      if (s ~ /^@media/ && s ~ /prefers-color-scheme/ && s ~ /dark/) return "darkmedia"
      if (s ~ /^@/) return "other"
      if (s == ":root") return "root"
      n = split(s, parts, ",")
      alldark = (n > 0)
      for (i = 1; i <= n; i++) {
        p = parts[i]
        gsub(/[ \t]/, "", p)
        if (p !~ /^((:root|html)?\.dark|(:root)?\[data-theme=("dark"|\047dark\047|dark)\])$/ && \
            p !~ /^(\.dark|\[data-theme=("dark"|\047dark\047|dark)\]):root$/) alldark = 0
      }
      return alldark ? "dark" : "other"
    }
    # the chain of non-layer blocks we are in, as "a/b/c"
    function chain(   i, c) {
      c = ""
      for (i = 1; i <= depth; i++) if (kd[i] != "layer") c = (c == "" ? kd[i] : c "/" kd[i])
      return c
    }
    {
      # CRLF files: a \r would stay in the selector (".dark\r" is not dark) and in values.
      gsub(/\r/, "")
      line = $0
      start_clean = (!incomment && quote == "")
      ctx = chain()
      for (i = 1; i <= length(line); i++) {
        ch = substr(line, i, 1)
        if (incomment) {
          if (ch == "*" && substr(line, i + 1, 1) == "/") { incomment = 0; i++ }
          continue
        }
        if (quote != "") {
          buf = buf ch
          if (ch == "\\") { buf = buf substr(line, i + 1, 1); i++ }
          else if (ch == quote) quote = ""
          continue
        }
        if (ch == "/" && substr(line, i + 1, 1) == "*") { incomment = 1; i++; continue }
        if (ch == "\"" || ch == "\047") { quote = ch; buf = buf ch; continue }
        if (ch == "{") { kd[++depth] = kind(buf); buf = "" }
        else if (ch == "}") { if (depth > 0) depth--; buf = "" }
        else if (ch == ";") buf = ""
        else buf = buf ch
      }
      if (buf != "") buf = buf " "
      if (!start_clean || line !~ /^[ \t]*--/) next
      if (mode == "light" && ctx == "root") print line
      else if (mode == "dark" && ctx == "dark") print line
      else if (mode == "media" && ctx == "darkmedia/root") print line
    }
  ' "$1" 2>/dev/null || true
}

CSS_CANDIDATES=("$PROJECT_DIR/src/index.css" "$PROJECT_DIR/src/styles/globals.css" "$PROJECT_DIR/src/app/globals.css" "$PROJECT_DIR/src/main.css" "$PROJECT_DIR/src/styles.css")
for css_file in "${CSS_CANDIDATES[@]}"; do
  [[ -f "$css_file" ]] || continue
  CSS_VARS=$(css_vars "$css_file" light)
  # The first file that has :root variables wins; a file without them is skipped.
  [[ -n "$CSS_VARS" ]] || continue
  DARK_VARS=$(css_vars "$css_file" dark)
  if [[ -z "$DARK_VARS" ]]; then
    DARK_VARS=$(css_vars "$css_file" media)
  fi
  CSS_FILE_FOUND="$css_file"
  break
done
if [[ -z "$CSS_VARS" ]]; then
  echo "WARNING: no :root custom properties found in $PROJECT_DIR (looked in src/index.css, src/styles/globals.css, src/app/globals.css, src/main.css, src/styles.css)" >&2
fi

# --- Extract font families from Tailwind config ---
TAILWIND_FONTS=""
for tw_config in "$PROJECT_DIR/tailwind.config.js" "$PROJECT_DIR/tailwind.config.ts" "$PROJECT_DIR/tailwind.config.mjs"; do
  if [[ -f "$tw_config" ]]; then
    TAILWIND_FONTS=$(grep -A 3 'fontFamily' "$tw_config" 2>/dev/null | grep -oE "'[^']+'" | tr -d "'" || true)
    TAILWIND_CONFIG_FOUND="$tw_config"
    break
  fi
done

# --- Output ---
case "$FORMAT" in
  html)
    echo "<!-- Design tokens extracted from: $PROJECT_DIR -->"
    echo "<!-- Generated by extract-design-tokens.sh -->"
    echo ""
    if [[ -n "$GOOGLE_FONTS_LINK" ]]; then
      echo "<!-- Google Fonts -->"
      echo "<link rel=\"preconnect\" href=\"https://fonts.googleapis.com\">"
      echo "<link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin>"
      echo "$GOOGLE_FONTS_LINK"
      echo ""
    fi
    echo "<style>"
    echo "  :root {"
    if [[ -n "$CSS_VARS" ]]; then
      echo "$CSS_VARS"
    else
      echo "    /* No CSS custom properties found in project */"
    fi
    echo "  }"
    if [[ -n "$DARK_VARS" ]]; then
      echo ""
      echo "  .dark {"
      echo "$DARK_VARS"
      echo "  }"
    fi
    echo "</style>"
    echo ""
    echo "<!-- Source files: -->"
    if [[ -n "$CSS_FILE_FOUND" ]]; then
      echo "<!-- CSS: $CSS_FILE_FOUND -->"
    fi
    if [[ -n "$TAILWIND_CONFIG_FOUND" ]]; then
      echo "<!-- Tailwind: $TAILWIND_CONFIG_FOUND -->"
    fi
    if [[ -n "$TAILWIND_FONTS" ]]; then
      echo "<!-- Tailwind fonts: $TAILWIND_FONTS -->"
    fi
    exit 0
    ;;

  json)
    if ! command -v jq >/dev/null 2>&1; then
      echo "Error: --format json needs jq" >&2
      exit 1
    fi
    # jq builds the JSON, so a quote or backslash in a path or a value cannot break it.
    # A value that was not found is null. Each variable line loses its leading whitespace.
    jq -n \
      --arg source "$PROJECT_DIR" \
      --arg googleFontsUrl "$GOOGLE_FONTS_URL" \
      --arg cssFile "$CSS_FILE_FOUND" \
      --arg tailwindConfig "$TAILWIND_CONFIG_FOUND" \
      --arg cssVariables "$(printf '%s' "$CSS_VARS" | sed 's/^[[:space:]]*//')" \
      --arg darkModeVariables "$(printf '%s' "$DARK_VARS" | sed 's/^[[:space:]]*//')" \
      --arg tailwindFonts "$TAILWIND_FONTS" \
      '{
        source: $source,
        googleFontsUrl: (if $googleFontsUrl == "" then null else $googleFontsUrl end),
        cssFile: (if $cssFile == "" then null else $cssFile end),
        tailwindConfig: (if $tailwindConfig == "" then null else $tailwindConfig end),
        cssVariables: (if $cssVariables == "" then null else $cssVariables end),
        darkModeVariables: (if $darkModeVariables == "" then null else $darkModeVariables end),
        tailwindFonts: (if $tailwindFonts == "" then null else $tailwindFonts end)
      }'
    ;;

  css)
    echo "/* Design tokens from: $PROJECT_DIR */"
    echo ":root {"
    if [[ -n "$CSS_VARS" ]]; then
      echo "$CSS_VARS"
    fi
    echo "}"
    if [[ -n "$DARK_VARS" ]]; then
      echo ""
      echo ".dark {"
      echo "$DARK_VARS"
      echo "}"
    fi
    exit 0
    ;;

  *)
    echo "Error: Unknown format '$FORMAT'. Use html, json, or css." >&2
    exit 2
    ;;
esac
