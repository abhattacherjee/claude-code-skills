#!/usr/bin/env bash
set -eu

# discover-project-architecture.sh — Scans a project to detect architecture layers,
# key services, test frameworks, API patterns, and data flow for spec review.
#
# Usage:
#   ./discover-project-architecture.sh <project-root>           # Human-readable report
#   ./discover-project-architecture.sh <project-root> --json    # JSON for agent consumption
#   ./discover-project-architecture.sh --help

usage() {
    cat <<EOF
Usage: $(basename "$0") <project-root> [--json]

Discovers project architecture for spec review agents.

Arguments:
  project-root   Path to the project root directory
  --json         Output as JSON (for agent consumption)
  --help         Show this help

Examples:
  $(basename "$0") /path/to/my-project
  $(basename "$0") . --json

Discovers:
  - Package directories (monorepo detection)
  - Architecture layers (frontend, backend, API, MCP, etc.)
  - Key services and controllers per layer
  - Test frameworks (unit, API, E2E)
  - API routes and endpoints
  - Framework detection (Express, Next.js, Django, Rails, etc.)
  - Data flow patterns between layers
EOF
    exit 0
}

[[ $# -lt 1 ]] && { echo "Error: project root required. Use --help for usage." >&2; exit 2; }
[[ "$1" == "--help" || "$1" == "-h" ]] && usage

PROJECT_ROOT="$1"
JSON_MODE=false
[[ "${2:-}" == "--json" ]] && JSON_MODE=true

if [[ ! -d "$PROJECT_ROOT" ]]; then
    echo "Error: Directory not found: $PROJECT_ROOT" >&2
    exit 1
fi

cd "$PROJECT_ROOT"

# --- Utility ---

json_escape() {
    local str="$1"
    str="${str//\\/\\\\}"
    str="${str//\"/\\\"}"
    str="${str//$'\n'/\\n}"
    str="${str//$'\t'/\\t}"
    printf '%s' "$str"
}

# --- Detection functions ---

detect_packages() {
    # Find directories with package.json, Cargo.toml, pyproject.toml, go.mod, etc.
    local pkgs=""
    # Node/JS packages
    for pj in $(find . -maxdepth 3 -name "package.json" -not -path "*/node_modules/*" -not -path "*/.next/*" -not -path "*/dist/*" 2>/dev/null | sort); do
        local dir
        dir=$(dirname "$pj" | sed 's|^\./||')
        [[ "$dir" == "." ]] && dir="root"
        local name
        name=$(grep -m1 '"name"' "$pj" 2>/dev/null | sed 's/.*"name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/' || echo "$dir")
        pkgs="${pkgs}${dir}:${name}\n"
    done
    # Python packages
    for pf in $(find . -maxdepth 3 \( -name "pyproject.toml" -o -name "setup.py" \) -not -path "*/venv/*" 2>/dev/null | sort); do
        local dir
        dir=$(dirname "$pf" | sed 's|^\./||')
        [[ "$dir" == "." ]] && dir="root"
        pkgs="${pkgs}${dir}:python-pkg\n"
    done
    # Go
    for gm in $(find . -maxdepth 3 -name "go.mod" 2>/dev/null | sort); do
        local dir
        dir=$(dirname "$gm" | sed 's|^\./||')
        [[ "$dir" == "." ]] && dir="root"
        pkgs="${pkgs}${dir}:go-mod\n"
    done
    # Rust
    for ct in $(find . -maxdepth 3 -name "Cargo.toml" -not -path "*/target/*" 2>/dev/null | sort); do
        local dir
        dir=$(dirname "$ct" | sed 's|^\./||')
        [[ "$dir" == "." ]] && dir="root"
        pkgs="${pkgs}${dir}:rust-crate\n"
    done
    printf '%b' "$pkgs" | grep -v '^$' | sort -u
}

classify_layer() {
    local dir="$1"
    local lower
    lower=$(echo "$dir" | tr '[:upper:]' '[:lower:]')

    # Frontend indicators
    if [[ -f "$dir/vite.config.ts" || -f "$dir/vite.config.js" || \
          -f "$dir/next.config.js" || -f "$dir/next.config.ts" || \
          -f "$dir/next.config.mjs" || \
          -f "$dir/nuxt.config.ts" || -f "$dir/svelte.config.js" || \
          -f "$dir/angular.json" ]]; then
        echo "frontend"
        return
    fi
    if echo "$lower" | grep -qE 'frontend|client|web|app|ui'; then
        # Verify it's not a mobile app directory
        if [[ -d "$dir/src" ]] || [[ -d "$dir/pages" ]] || [[ -d "$dir/components" ]]; then
            echo "frontend"
            return
        fi
    fi

    # Backend/API indicators — check BEFORE MCP since a backend may call MCP as a client
    if echo "$lower" | grep -qE '^backend$|^server$|^api$'; then
        echo "backend"
        return
    fi
    if [[ -f "$dir/package.json" ]] && [[ -d "$dir/src" ]]; then
        if grep -q '"express"\|"fastify"\|"koa"\|"hapi"\|"@nestjs/core"' "$dir/package.json" 2>/dev/null; then
            # Check if it's actually an MCP server (hosts MCP, not just calls it)
            if echo "$lower" | grep -qE 'mcp'; then
                echo "mcp"
                return
            fi
            echo "backend"
            return
        fi
    fi

    # MCP server indicators
    if echo "$lower" | grep -qE 'mcp'; then
        echo "mcp"
        return
    fi
    if [[ -d "$dir/src" ]] && grep -rlq "McpServer\|createServer.*mcp\|@modelcontextprotocol" "$dir/src/" 2>/dev/null; then
        echo "mcp"
        return
    fi

    # Generic backend by name
    if echo "$lower" | grep -qE 'service'; then
        echo "backend"
        return
    fi

    # Python backends
    if [[ -f "$dir/manage.py" ]] || grep -q "django\|flask\|fastapi" "$dir/requirements.txt" 2>/dev/null || \
       grep -q "django\|flask\|fastapi" "$dir/pyproject.toml" 2>/dev/null; then
        echo "backend"
        return
    fi

    # Tools/scripts
    if echo "$lower" | grep -qE 'tools|scripts|utils|infra|deployment|docs'; then
        echo "tooling"
        return
    fi

    echo "unknown"
}

detect_framework() {
    local dir="$1"
    local frameworks=""

    # JavaScript/TypeScript frameworks
    if [[ -f "$dir/package.json" ]]; then
        local pkg="$dir/package.json"
        grep -q '"react"' "$pkg" 2>/dev/null && frameworks="${frameworks}React,"
        grep -q '"next"' "$pkg" 2>/dev/null && frameworks="${frameworks}Next.js,"
        grep -q '"vue"' "$pkg" 2>/dev/null && frameworks="${frameworks}Vue,"
        grep -q '"nuxt"' "$pkg" 2>/dev/null && frameworks="${frameworks}Nuxt,"
        grep -q '"svelte"' "$pkg" 2>/dev/null && frameworks="${frameworks}Svelte,"
        grep -q '"angular"' "$pkg" 2>/dev/null && frameworks="${frameworks}Angular,"
        grep -q '"express"' "$pkg" 2>/dev/null && frameworks="${frameworks}Express,"
        grep -q '"fastify"' "$pkg" 2>/dev/null && frameworks="${frameworks}Fastify,"
        grep -q '"@nestjs/core"' "$pkg" 2>/dev/null && frameworks="${frameworks}NestJS,"
        grep -q '"hono"' "$pkg" 2>/dev/null && frameworks="${frameworks}Hono,"
        grep -q '"koa"' "$pkg" 2>/dev/null && frameworks="${frameworks}Koa,"
        grep -q '"@modelcontextprotocol"' "$pkg" 2>/dev/null && frameworks="${frameworks}MCP-SDK,"
        grep -q '"vite"' "$pkg" 2>/dev/null && frameworks="${frameworks}Vite,"
        grep -q '"tailwindcss"' "$pkg" 2>/dev/null && frameworks="${frameworks}Tailwind,"
    fi

    # Python frameworks
    for pyf in "$dir/requirements.txt" "$dir/pyproject.toml" "$dir/setup.py"; do
        if [[ -f "$pyf" ]]; then
            grep -qi "django" "$pyf" 2>/dev/null && frameworks="${frameworks}Django,"
            grep -qi "flask" "$pyf" 2>/dev/null && frameworks="${frameworks}Flask,"
            grep -qi "fastapi" "$pyf" 2>/dev/null && frameworks="${frameworks}FastAPI,"
        fi
    done

    echo "$frameworks" | sed 's/,$//'
}

find_services() {
    local dir="$1"
    local max_results=15
    # Find service, controller, handler, middleware, route files in src/ only
    # Excludes: node_modules, dist, coverage, tests, .next, .vite, build artifacts
    find "$dir" -maxdepth 4 -type f \
        \( -name "*[Ss]ervice.*" -o -name "*[Cc]ontroller.*" -o -name "*[Hh]andler.*" \
           -o -name "*[Mm]iddleware.*" -o -name "*[Rr]outer.*" -o -name "*[Rr]oute.*" -o -name "*[Rr]outes.*" \) \
        -not -path "*/node_modules/*" -not -path "*/dist/*" -not -path "*/__pycache__/*" \
        -not -path "*/.next/*" -not -path "*/.vite/*" -not -path "*/coverage/*" \
        -not -path "*/tests/*" -not -path "*/test/*" -not -path "*/__tests__/*" \
        -not -path "*/build/*" -not -path "*/.cache/*" \
        -not -name "*.test.*" -not -name "*.spec.*" -not -name "*.html" -not -name "*.map" \
        2>/dev/null | head -"$max_results" | sed "s|^\./||"
}

detect_test_frameworks() {
    local dir="$1"
    local tests=""

    if [[ -f "$dir/package.json" ]]; then
        local pkg="$dir/package.json"
        grep -q '"jest"' "$pkg" 2>/dev/null && tests="${tests}Jest,"
        grep -q '"vitest"' "$pkg" 2>/dev/null && tests="${tests}Vitest,"
        grep -q '"mocha"' "$pkg" 2>/dev/null && tests="${tests}Mocha,"
        grep -q '"@playwright/test"' "$pkg" 2>/dev/null && tests="${tests}Playwright,"
        grep -q '"cypress"' "$pkg" 2>/dev/null && tests="${tests}Cypress,"
    fi
    # Python
    [[ -f "$dir/pytest.ini" || -f "$dir/conftest.py" ]] && tests="${tests}pytest,"
    grep -q "pytest" "$dir/pyproject.toml" 2>/dev/null && tests="${tests}pytest,"

    echo "$tests" | sed 's/,$//'
}

detect_api_test_tools() {
    # Bruno
    local tools=""
    if find . -maxdepth 4 -name "*.bru" -not -path "*/node_modules/*" 2>/dev/null | head -1 | grep -q .; then
        local bru_count
        bru_count=$(find . -maxdepth 5 -name "*.bru" -not -path "*/node_modules/*" 2>/dev/null | wc -l | tr -d ' ')
        local bru_dirs
        bru_dirs=$(find . -maxdepth 4 -name "*.bru" -not -path "*/node_modules/*" 2>/dev/null | \
            xargs -I{} dirname {} | sort -u | sed 's|^\./||' | head -10)
        tools="${tools}Bruno(${bru_count} files),"
    fi
    # Postman
    find . -maxdepth 3 -name "*postman*" -name "*.json" -not -path "*/node_modules/*" 2>/dev/null | \
        head -1 | grep -q . && tools="${tools}Postman,"
    # Insomnia
    find . -maxdepth 3 -name ".insomnia" -type d 2>/dev/null | head -1 | grep -q . && tools="${tools}Insomnia,"
    # HTTP files (VS Code REST Client)
    find . -maxdepth 4 -name "*.http" -not -path "*/node_modules/*" 2>/dev/null | \
        head -1 | grep -q . && tools="${tools}HTTPClient,"

    echo "$tools" | sed 's/,$//'
}

detect_bruno_folders() {
    # Find Bruno test folder structure
    local bru_root
    bru_root=$(find . -maxdepth 3 -name "bruno.json" -not -path "*/node_modules/*" 2>/dev/null | head -1)
    if [[ -n "$bru_root" ]]; then
        local bru_dir
        bru_dir=$(dirname "$bru_root")
        # List immediate subdirectories that contain .bru files
        # Exclude environments/ (Bruno env configs, not test folders)
        for d in "$bru_dir"/*/; do
            [[ -d "$d" ]] || continue
            local name
            name=$(basename "$d")
            # Skip known non-test directories
            [[ "$name" == "environments" || "$name" == "collection" ]] && continue
            find "$d" -maxdepth 1 -name "*.bru" 2>/dev/null | head -1 | grep -q . && \
                echo "$name"
        done | sort
    fi
}

detect_e2e_framework() {
    local found=""
    # Playwright
    if [[ -f "playwright.config.ts" || -f "playwright.config.js" ]]; then
        found="${found}Playwright,"
    fi
    for d in $(find . -maxdepth 3 -name "playwright.config.*" -not -path "*/node_modules/*" 2>/dev/null); do
        echo "$found" | grep -q "Playwright" || found="${found}Playwright,"
    done
    # Cypress
    if [[ -f "cypress.config.ts" || -f "cypress.config.js" || -d "cypress" ]]; then
        found="${found}Cypress,"
    fi
    echo "$found" | sed 's/,$//'
}

detect_data_flow() {
    # Detect inter-layer communication patterns
    local patterns=""

    # HTTP client calls between services
    if grep -rl "fetch\|axios\|got\|node-fetch\|HttpClient" . \
        --include="*.ts" --include="*.js" --include="*.py" \
        2>/dev/null | grep -qv node_modules; then
        patterns="${patterns}HTTP-inter-service,"
    fi

    # Proxy configuration (Vite, webpack, etc.). Published packages do ship
    # their own vite.config.js/webpack.config.js, so this needs the same
    # node_modules filter as every other guard.
    if grep -rl "proxy.*localhost\|proxy.*127.0.0.1" . \
        --include="vite.config.*" --include="webpack.config.*" --include="next.config.*" \
        2>/dev/null | grep -qv node_modules; then
        patterns="${patterns}Dev-proxy,"
    fi

    # Message queue / event system
    if grep -rl "amqp\|rabbitmq\|redis.*pub\|kafka\|bull\|EventEmitter" . \
        --include="*.ts" --include="*.js" --include="*.py" \
        2>/dev/null | grep -qv node_modules; then
        patterns="${patterns}Event-messaging,"
    fi

    # Database
    if grep -rl "prisma\|sequelize\|typeorm\|mongoose\|knex\|drizzle\|pg\|mysql" . \
        --include="package.json" --include="*.toml" \
        2>/dev/null | grep -qv node_modules; then
        patterns="${patterns}Database,"
    fi

    # GraphQL
    if grep -rl "graphql\|apollo\|@graphql" . \
        --include="package.json" \
        2>/dev/null | grep -qv node_modules; then
        patterns="${patterns}GraphQL,"
    fi

    # REST
    if grep -rl "router\.\(get\|post\|put\|delete\)\|@Get\|@Post\|app\.\(get\|post\)" . \
        --include="*.ts" --include="*.js" \
        2>/dev/null | grep -qv node_modules; then
        patterns="${patterns}REST-API,"
    fi

    echo "$patterns" | sed 's/,$//'
}

detect_i18n() {
    local i18n=""
    # React i18next
    if grep -rl "i18next\|react-i18next\|useTranslation" . \
        --include="package.json" --include="*.ts" --include="*.tsx" \
        2>/dev/null | grep -qv node_modules; then
        i18n="${i18n}i18next,"
    fi
    # Vue i18n
    if grep -rl "vue-i18n" . --include="package.json" \
        2>/dev/null | grep -qv node_modules; then
        i18n="${i18n}vue-i18n,"
    fi
    # Bilingual text patterns
    if grep -rl "BilingualText\|{ en:.*pt:\|{ en:.*es:" . \
        --include="*.ts" --include="*.js" \
        2>/dev/null | grep -qv node_modules; then
        i18n="${i18n}BilingualText,"
    fi
    # Locale directories
    find . -maxdepth 5 -type d -name "locales" -not -path "*/node_modules/*" 2>/dev/null | \
        head -1 | grep -q . && i18n="${i18n}LocaleFiles,"

    echo "$i18n" | sed 's/,$//'
}

detect_security_patterns() {
    local sec=""
    if grep -rl "csrf\|csurf\|double.submit" . --include="*.ts" --include="*.js" \
        2>/dev/null | grep -qv node_modules; then
        sec="${sec}CSRF,"
    fi
    if grep -rl "helmet\|csp\|Content-Security-Policy" . --include="*.ts" --include="*.js" \
        2>/dev/null | grep -qv node_modules; then
        sec="${sec}Helmet/CSP,"
    fi
    if grep -rl "rate.limit\|rateLimit\|express-rate-limit" . --include="*.ts" --include="*.js" --include="package.json" \
        2>/dev/null | grep -qv node_modules; then
        sec="${sec}RateLimit,"
    fi
    if grep -rl "cors\|CORS\|Access-Control" . --include="*.ts" --include="*.js" \
        2>/dev/null | grep -qv node_modules; then
        sec="${sec}CORS,"
    fi

    echo "$sec" | sed 's/,$//'
}

# --- Run discovery ---

PACKAGES=$(detect_packages)
API_TEST_TOOLS=$(detect_api_test_tools)
E2E_FRAMEWORK=$(detect_e2e_framework)
DATA_FLOW=$(detect_data_flow)
I18N=$(detect_i18n)
SECURITY=$(detect_security_patterns)

# --- Output ---

if $JSON_MODE; then
    # Build layers array
    LAYERS_JSON="["
    FIRST=true
    while IFS=: read -r dir name; do
        [[ -z "$dir" ]] && continue
        local_dir="$dir"
        [[ "$dir" == "root" ]] && local_dir="."
        layer=$(classify_layer "$local_dir")
        framework=$(detect_framework "$local_dir")
        tests=$(detect_test_frameworks "$local_dir")
        services=$(find_services "$local_dir" | head -10)

        services_json="["
        S_FIRST=true
        while IFS= read -r svc; do
            [[ -z "$svc" ]] && continue
            if $S_FIRST; then S_FIRST=false; else services_json+=","; fi
            services_json+="\"$(json_escape "$svc")\""
        done <<< "$services"
        services_json+="]"

        if $FIRST; then FIRST=false; else LAYERS_JSON+=","; fi
        LAYERS_JSON+="{\"directory\":\"$(json_escape "$dir")\",\"name\":\"$(json_escape "$name")\",\"layer\":\"$layer\",\"frameworks\":\"$(json_escape "$framework")\",\"testFrameworks\":\"$(json_escape "$tests")\",\"services\":$services_json}"
    done <<< "$PACKAGES"
    LAYERS_JSON+="]"

    # Bruno folders
    BRUNO_JSON="["
    FIRST=true
    while IFS= read -r folder; do
        [[ -z "$folder" ]] && continue
        if $FIRST; then FIRST=false; else BRUNO_JSON+=","; fi
        BRUNO_JSON+="\"$(json_escape "$folder")\""
    done < <(detect_bruno_folders)
    BRUNO_JSON+="]"

    cat <<ENDJSON
{
  "packages": $LAYERS_JSON,
  "apiTestTools": "$(json_escape "$API_TEST_TOOLS")",
  "e2eFramework": "$(json_escape "$E2E_FRAMEWORK")",
  "brunoFolders": $BRUNO_JSON,
  "dataFlow": "$(json_escape "$DATA_FLOW")",
  "i18n": "$(json_escape "$I18N")",
  "security": "$(json_escape "$SECURITY")"
}
ENDJSON

else
    echo "=== Project Architecture Discovery ==="
    echo ""

    echo "--- Packages / Layers ---"
    while IFS=: read -r dir name; do
        [[ -z "$dir" ]] && continue
        local_dir="$dir"
        [[ "$dir" == "root" ]] && local_dir="."
        layer=$(classify_layer "$local_dir")
        framework=$(detect_framework "$local_dir")
        tests=$(detect_test_frameworks "$local_dir")
        printf "  %-25s %-10s  %s  [tests: %s]\n" "$dir ($name)" "[$layer]" "$framework" "$tests"
    done <<< "$PACKAGES"
    echo ""

    echo "--- Key Services ---"
    while IFS=: read -r dir name; do
        [[ -z "$dir" ]] && continue
        local_dir="$dir"
        [[ "$dir" == "root" ]] && local_dir="."
        services=$(find_services "$local_dir")
        if [[ -n "$services" ]]; then
            echo "  $dir:"
            echo "$services" | sed 's/^/    /'
        fi
    done <<< "$PACKAGES"
    echo ""

    echo "--- API Test Tools ---"
    echo "  ${API_TEST_TOOLS:-none detected}"
    echo ""

    if [[ -n "$(detect_bruno_folders)" ]]; then
        echo "--- Bruno Test Folders ---"
        detect_bruno_folders | sed 's/^/  /'
        echo ""
    fi

    echo "--- E2E Framework ---"
    echo "  ${E2E_FRAMEWORK:-none detected}"
    echo ""

    echo "--- Data Flow Patterns ---"
    echo "  ${DATA_FLOW:-none detected}"
    echo ""

    echo "--- i18n ---"
    echo "  ${I18N:-none detected}"
    echo ""

    echo "--- Security Patterns ---"
    echo "  ${SECURITY:-none detected}"
    echo ""
fi
