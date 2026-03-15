#!/usr/bin/env bash
set -eu

# Capture mobile screenshots of a web app for use in Remotion product videos.
# Uses Playwright to render pages in a mobile viewport with 2x DPR.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS] <output-dir>

Capture mobile screenshots of a running web app for Remotion product videos.

Options:
  --url <url>              Base URL of the app (default: http://localhost:5173)
  --shared-url <url>       URL of a shared/results page to capture
  --viewport <WxH>         Mobile viewport size (default: 390x844)
  --dpr <n>                Device pixel ratio (default: 2)
  --hide-selectors <sel>   CSS selectors to hide before capture (comma-separated)
  --flow-script <file>     Node.js script for custom flow capture
  --fullpage               Capture full-page screenshots for scrolling effects
  -h, --help               Show this help

Examples:
  $(basename "$0") ./public/screenshots --url http://localhost:5173
  $(basename "$0") ./public/screenshots --shared-url https://app.example.com/shared/abc123
  $(basename "$0") ./public/screenshots --fullpage --hide-selectors ".fixed,.theme-toggle"

EOF
  exit 0
}

# Defaults
APP_URL="http://localhost:5173"
SHARED_URL=""
VIEWPORT="390x844"
DPR=2
HIDE_SELECTORS=".fixed"
FLOW_SCRIPT=""
FULLPAGE=false
OUTPUT_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --url) APP_URL="$2"; shift 2 ;;
    --shared-url) SHARED_URL="$2"; shift 2 ;;
    --viewport) VIEWPORT="$2"; shift 2 ;;
    --dpr) DPR="$2"; shift 2 ;;
    --hide-selectors) HIDE_SELECTORS="$2"; shift 2 ;;
    --flow-script) FLOW_SCRIPT="$2"; shift 2 ;;
    --fullpage) FULLPAGE=true; shift ;;
    -h|--help) usage ;;
    -*) echo "Unknown option: $1" >&2; exit 2 ;;
    *) OUTPUT_DIR="$1"; shift ;;
  esac
done

if [[ -z "$OUTPUT_DIR" ]]; then
  echo "Error: output directory is required" >&2
  usage
fi

mkdir -p "$OUTPUT_DIR"

VP_W="${VIEWPORT%x*}"
VP_H="${VIEWPORT#*x}"

# Check if playwright is available
if ! node -e "require('playwright')" 2>/dev/null; then
  echo "Installing playwright..."
  npm install --no-save playwright 2>/dev/null
  npx playwright install chromium 2>/dev/null
fi

# Generate the capture script
CAPTURE_SCRIPT=$(mktemp /tmp/capture-XXXXXX.mjs)
trap "rm -f $CAPTURE_SCRIPT" EXIT

cat > "$CAPTURE_SCRIPT" <<SCRIPT
import { chromium } from "playwright";
import { mkdirSync } from "fs";

const OUTPUT = "${OUTPUT_DIR}";
const VP = { width: ${VP_W}, height: ${VP_H} };
const DPR = ${DPR};
const HIDE = "${HIDE_SELECTORS}";
const APP_URL = "${APP_URL}";
const SHARED_URL = "${SHARED_URL}";
const FULLPAGE = ${FULLPAGE};

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

  await browser.close();
  console.log("\\nDone! Screenshots saved to " + OUTPUT);
}

run().catch(console.error);
SCRIPT

node "$CAPTURE_SCRIPT"
