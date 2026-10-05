#!/usr/bin/env bash
set -eu

# Capture mobile screenshots of a web app for use in Remotion product videos.
# Uses Playwright to render pages in a mobile viewport with 2x DPR.

usage() {
  local rc="${1:-0}"
  cat <<EOF
Usage: $(basename "$0") [OPTIONS] <output-dir>

Capture mobile screenshots of a running web app for Remotion product videos.
Run it from your project directory: the playwright package is loaded (and, if
missing, installed with npm) there.

Options:
  --url <url>              Base URL of the app (default: http://localhost:5173)
  --shared-url <url>       URL of a shared/results page to capture
  --viewport <WxH>         Mobile viewport size (default: 390x844)
  --dpr <n>                Device pixel ratio (default: 2)
  --hide-selectors <sel>   CSS selectors to hide before capture (comma-separated)
  --fullpage               Capture full-page screenshots for scrolling effects
  -h, --help               Show this help

For a custom click-through flow, write your own Playwright script.

Examples:
  $(basename "$0") ./public/screenshots --url http://localhost:5173
  $(basename "$0") ./public/screenshots --shared-url https://app.example.com/shared/abc123
  $(basename "$0") ./public/screenshots --fullpage --hide-selectors ".fixed,.theme-toggle"

EOF
  exit "$rc"
}

# Defaults
APP_URL="http://localhost:5173"
SHARED_URL=""
VIEWPORT="390x844"
DPR=2
HIDE_SELECTORS=".fixed"
FULLPAGE=false
OUTPUT_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --url|--shared-url|--viewport|--dpr|--hide-selectors)
      if [[ $# -lt 2 ]]; then
        echo "Option $1 needs a value" >&2
        exit 2
      fi ;;
  esac
  case "$1" in
    --url) APP_URL="$2"; shift 2 ;;
    --shared-url) SHARED_URL="$2"; shift 2 ;;
    --viewport) VIEWPORT="$2"; shift 2 ;;
    --dpr) DPR="$2"; shift 2 ;;
    --hide-selectors) HIDE_SELECTORS="$2"; shift 2 ;;
    --fullpage) FULLPAGE=true; shift ;;
    -h|--help) usage 0 ;;
    -*) echo "Unknown option: $1" >&2; exit 2 ;;
    *) OUTPUT_DIR="$1"; shift ;;
  esac
done

if [[ -z "$OUTPUT_DIR" ]]; then
  echo "Error: output directory is required" >&2
  usage 2 >&2
fi

if ! [[ "$VIEWPORT" =~ ^[0-9]+x[0-9]+$ ]]; then
  echo "Error: --viewport must be WIDTHxHEIGHT, for example 390x844, got: $VIEWPORT" >&2
  exit 2
fi
if ! [[ "$DPR" =~ ^[0-9]+(\.[0-9]+)?$ ]]; then
  echo "Error: --dpr must be a number, got: $DPR" >&2
  exit 2
fi

if ! command -v node >/dev/null 2>&1; then
  echo "Error: node is required (https://nodejs.org)." >&2
  exit 1
fi

mkdir -p "$OUTPUT_DIR"

# Load playwright from the current directory; install it there if missing.
if ! node -e 'require.resolve("playwright")' >/dev/null 2>&1; then
  echo "Installing playwright in $PWD ..."
  if ! NPM_OUT=$(npm install --no-save playwright 2>&1); then
    printf '%s\n' "$NPM_OUT" | tail -n 5 >&2
    echo "Error: npm install playwright failed in $PWD" >&2
    exit 1
  fi
  if ! NPX_OUT=$(npx playwright install chromium 2>&1); then
    printf '%s\n' "$NPX_OUT" | tail -n 5 >&2
    echo "Error: npx playwright install chromium failed" >&2
    exit 1
  fi
  if ! node -e 'require.resolve("playwright")' >/dev/null 2>&1; then
    echo "Error: the playwright package still cannot be loaded from $PWD after npm install" >&2
    exit 1
  fi
fi

# The JavaScript below is fixed text. Every value reaches it through an
# environment variable, never by pasting it into the code, so a quote in a URL
# or selector cannot break or change the program. It runs with
# `node --input-type=module -e`, so `import "playwright"` resolves from the
# current directory, where the package is installed. No temp .mjs file.
read -r -d '' CAPTURE_JS <<'JS' || true
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const env = process.env;
const OUTPUT = env.CAP_OUTPUT;
const VP = { width: Number(env.CAP_VP_W), height: Number(env.CAP_VP_H) };
const DPR = Number(env.CAP_DPR);
const HIDE = env.CAP_HIDE || "";
const APP_URL = env.CAP_APP_URL;
const SHARED_URL = env.CAP_SHARED_URL || "";
const FULLPAGE = env.CAP_FULLPAGE === "true";

mkdirSync(OUTPUT, { recursive: true });

async function hide(page) {
  if (!HIDE) return;
  await page.evaluate((sel) => {
    sel.split(",").forEach(s => {
      document.querySelectorAll(s.trim()).forEach(el => el.style.display = "none");
    });
  }, HIDE);
  await page.waitForTimeout(200);
}

async function run() {
  const browser = await chromium.launch({ headless: true });
  try {
    const ctx = await browser.newContext({
      viewport: VP, deviceScaleFactor: DPR, isMobile: true, hasTouch: true,
    });
    const page = await ctx.newPage();

    // Hero screenshot
    await page.goto(APP_URL, { waitUntil: "networkidle" });
    await page.waitForTimeout(3000);
    await hide(page);
    await page.screenshot({ path: OUTPUT + "/hero.png" });
    console.log("✓ hero.png");

    if (FULLPAGE) {
      await page.screenshot({ path: OUTPUT + "/hero-fullpage.png", fullPage: true });
      console.log("✓ hero-fullpage.png");
    }

    // Shared/results page
    if (SHARED_URL) {
      await page.goto(SHARED_URL, { waitUntil: "networkidle" });
      await page.waitForTimeout(3000);
      await hide(page);
      await page.screenshot({ path: OUTPUT + "/results-top.png" });
      console.log("✓ results-top.png");

      await page.screenshot({ path: OUTPUT + "/results-fullpage.png", fullPage: true });
      const dims = await page.evaluate(() => ({
        scrollHeight: document.documentElement.scrollHeight,
        clientHeight: document.documentElement.clientHeight,
      }));
      console.log("✓ results-fullpage.png (" + dims.scrollHeight + "px tall)");

      // Scroll captures
      for (let i = 1; i <= 3; i++) {
        await page.evaluate(() => window.scrollBy(0, 600));
        await page.waitForTimeout(800);
        await page.screenshot({ path: OUTPUT + "/results-scroll-" + i + ".png" });
        console.log("✓ results-scroll-" + i + ".png");
      }
    }
  } finally {
    await browser.close();
  }
  console.log("\nDone! Screenshots saved to " + OUTPUT);
}

try {
  await run();
} catch (e) {
  console.error("Error: screenshot capture failed: " + (e && e.message ? e.message : e));
  process.exit(1);
}
JS

CAP_OUTPUT="$OUTPUT_DIR" CAP_VP_W="${VIEWPORT%x*}" CAP_VP_H="${VIEWPORT#*x}" CAP_DPR="$DPR" \
  CAP_HIDE="$HIDE_SELECTORS" CAP_APP_URL="$APP_URL" CAP_SHARED_URL="$SHARED_URL" CAP_FULLPAGE="$FULLPAGE" \
  node --input-type=module -e "$CAPTURE_JS"
