# Anthropic Claude MCP Connectors Directory — 10-Step Submission Playbook (Learned from ClauseGuard Live Submission)

Whenever preparing or assisting the user with submitting an MCP server (`schemaextract-mcp` / BillTally, `deckforge-mcp`, `clauseguard-mcp`, or any future MCP connector) to the **Claude Connectors Directory** (`claude.ai/admin-settings/directory/submissions/new`), you MUST proactively execute and verify every item below **BEFORE** the user starts Step 1 (because Step 1/2 caches `tools/list` on first connect).

---

## 1. Pre-Submission Code & Live Railway Deployment Checklist (MUST Deploy First!)

1. **Tool Annotations (`readOnlyHint: true` on ALL Stateless/Generator Tools):**
   - In `tools/list`, every stateless analysis, extraction, or artifact-generation tool (`audit_and_redline_contract`, `extract_document_schema`, `generate_executive_deck`, etc.) **MUST** set:
     ```json
     "annotations": {
       "title": "Human-Readable Tool Title",
       "readOnlyHint": true,
       "destructiveHint": false,
       "idempotentHint": true,
       "openWorldHint": false
     }
     ```
   - **Why:** If any tool has `"readOnlyHint": false`, Step 2 categorizes it under **`Write tools`**, and Step 4 (`Read/write capabilities`) throws a yellow validation warning if the user selects `Read only`.

2. **Every Single `inputSchema` Property MUST Have a Plain-English `description`:**
   - Step 2 (`Tools`) renders every parameter and its description directly in the submission review UI. Any property missing `"description"` looks incomplete in the reviewer table.
   - Ensure 100% of top-level and nested properties in `inputSchema` have a clear, plain-English `"description"`.
   - Remove raw XML/code tags (like `<w:del>`, `<p:sld>`, raw JSON snippets) from tool `title` and `description` strings.

3. **Remove Developer/Debug Drawers from the Customer-Facing Web UI:**
   - Do NOT show raw JSON-RPC 2.0 payloads, OAuth token debuggers, or developer manifest buttons on the main web app UI. Keep the web app 100% focused on the end-user workflow.

4. **Required Public Pages (Must Be Live on Railway HTTPS & Linked in Top Header):**
   - **`/docs` (and `/documentation`)**: Public **User & IT Administrator Documentation** page. Must set `FastAPI(docs_url="/openapi-docs")` so `/docs` serves the human-readable HTML documentation page (not Swagger UI!). Must document:
     - 100% Read-Only & Idempotent tool scope
     - Zero model training & ephemeral memory handling
     - TLS 1.3 + OAuth 2.1 PKCE discovery
     - Tool table & example prompts
     - Support email: `mulak1@gmail.com`
   - **`/about`**: Public **About & Company** page matching Step 5 (`Company` = product/brand name, `Founder & Creator` = `Kader Mula`, `Contact & Support` = `mulak1@gmail.com`).
   - **`/privacy`**: Plain-English Privacy & Confidentiality Policy with support email `mulak1@gmail.com`.
   - **`/terms`**: Plain-English Terms of Service & Disclaimer.
   - **Header Navigation:** Link `About` (`/about`), `Documentation` (`/docs`), `Privacy Policy` (`/privacy`), and `Terms` (`/terms`) visibly in the top header of `/`.

5. **Public GitHub Repository + Claude Plugin Manifest:**
   - Push the repository to `https://github.com/mulak1/<repo-name>` using the `mulak1` credentials in `git credential-osxkeychain`.
   - Include `.claude-plugin/plugin.json`, `.mcp.json` (pointing to `https://<service>.up.railway.app/mcp`), and a clean `README.md`.

6. **HTTPS Proxy Awareness on Railway:**
   - In `/.well-known/oauth-authorization-server` and any download URLs returned by `tools/call`, inspect `request.headers.get("x-forwarded-proto") == "https"` or `"railway.app" in base_url` and rewrite `http://` to `https://`.

---

## 2. Step-by-Step Answers for the 10-Step Claude Directory Submission Form

Always present the user with ready-to-paste blocks for all 10 steps:

- **Step 1 (Basic Info & Listing):**
  - **Name:** `<Brand>: <Plain-English Outcome>` (e.g., `ClauseGuard: Contract Redlines`, `BillTally: Invoice & Receipt Extractor`, `DeckForge: Executive Slide Decks`)
  - **Remote MCP Server URL:** `https://<service>.up.railway.app/mcp`
  - **Documentation URL:** `https://<service>.up.railway.app/docs`
  - **Support Email:** `mulak1@gmail.com`
  - **Privacy Policy URL:** `https://<service>.up.railway.app/privacy`
  - **Terms of Service URL:** `https://<service>.up.railway.app/terms`
- **Step 2 (Tools):**
  - Verify all tools appear under **`Read-only tools`** (`Read-only · Idempotent`) with descriptions on every parameter.
- **Step 3 (Categories):**
  - Select the 2–3 tightest-fit categories (e.g., `Productivity` + domain category such as `Legal`, `Financial Services`, or `Data & Analytics`).
- **Step 4 (Use cases):**
  - Provide **3 Use case + Example prompt** pairs where each Example prompt includes **inline sample data** so Anthropic's reviewer can copy-paste the prompt directly into Claude chat and get an instant, rich result without needing external files.
  - **Prerequisites:** `No account, API key, or external setup required. Works immediately upon connecting — reviewers can paste sample text or data directly into chat.`
  - **Read/write capabilities:** `Read only` (matches `readOnlyHint: true` on all tools).
- **Step 5 (Company):**
  - **Company name:** `<Brand Name>`
  - **Company website:** `https://<service>.up.railway.app` (or `/about`)
  - **Full name:** `Kader Mula`
  - **Email:** `mulak1@gmail.com`
  - **Role:** `Founder & Creator`
- **Step 6 (Authentication):**
  - **Authentication requirement:** `None ✓ Detected` (fastest review approval & 1-click user install).
  - **Setup guide for admins:** `https://<service>.up.railway.app/docs`
- **Step 7 (Data handling):**
  - **API ownership:** `We own the API` (first-party execution on our own server, zero third-party API calls).
  - **Personal health data:** `No`
  - **Sponsored or promoted content:** `No`
- **Step 8 (Test & launch):**
  - **Test setup instructions:** Provide 3 copy-paste test prompts (one per tool) with inline data and expected results, plus note that no login/credentials are required.
  - Check **`I have run every tool via MCP Inspector or as a custom connector in Claude`**.
- **Step 9 (Compliance):**
  - Check all 7 policy acknowledgement boxes.
  - **Additional notes:** Note that the server is stateless, first-party, processes data in ephemeral memory only, never trains on user data, and has live IT admin documentation at `/docs`.
- **Step 10 (Review & Submit):**
  - Submit!


---

## 3. OpenAI ChatGPT / Codex Public Plugin Directory Submission (`platform.openai.com/plugins`)

Learned from `https://developers.openai.com/plugins/deploy/submission.md`:

1. **Pre-Built Portable Agent Plugins `.zip` Package (`<app>-openai-plugin.zip`):**
   - OpenAI's developer portal (`https://platform.openai.com/plugins` → **Upload new or existing plugin**) accepts a `.zip` package that **auto-populates almost the entire listing AND review form** when structured using the Portable Agent Plugins format:
     - `plugin.json` at root with `"$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"` and `extensions.com.openai`:
       - `interface.displayName` (<= 30 chars)
       - `interface.shortDescription` (<= 30 chars)
       - `interface.longDescription` (<= 4000 chars)
       - `interface.developerName`: `"Kader Mula"`
       - `interface.category`: `"Business & Operations"` or `"Productivity"`
       - `interface.websiteURL`, `supportURL` (`/docs`), `privacyPolicyURL` (`/privacy`), `termsOfServiceURL` (`/terms`) — **all 4 URLs are required for MCP review!**
       - `interface.composerIcon`, `composerIconDark`, `logo`, `logoDark`, `screenshots` (`./assets/*.png`)
       - `onboardingSkill`: `"./skills/<skill-name>/SKILL.md"`
       - `review.test_cases.positive`: **EXACTLY 5 positive test cases** (`description`, `prompt`, `tools_triggered`, `expected_behavior`)
       - `review.test_cases.negative`: **EXACTLY 3 negative test cases** (`description`, `prompt`)
       - `review.demo_recording_url`, `review.commerce: false`, `review.commerce_description`
       - `publication.release_notes`
     - `mcp.json` at root with `"$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"` and `"type": "streamable-http"`, `"url": "https://<service>.up.railway.app/mcp"`.
     - **CRITICAL:** Do NOT include `.app.json` or `hooks/` in a public submission `.zip` (OpenAI rejects packages containing `.app.json` or lifecycle hooks).
2. **Domain Verification Endpoint (`/.well-known/openai-apps-challenge`):**
   - Expose `GET /.well-known/openai-apps-challenge` returning a `PlainTextResponse` with the exact token (and `POST /api/admin/openai-challenge` to update the token dynamically in 1 second when the user reaches the MCP Connect step on `platform.openai.com/plugins`).


6. **OpenAI MCP Tool Scan & Authentication Discovery Rules (Critical)**
   - **Declare `auth.type: "none"` in `mcp.json`**: Under `mcpServers.<name>.extensions["com.openai"].auth`, explicitly set `{"type": "none"}` for unauthenticated public MCP servers.
   - **Return `HTTP 404` on `GET /.well-known/oauth-authorization-server` on production HTTPS**: OpenAI's MCP scanner probes 9 OAuth/OIDC discovery paths (`/.well-known/oauth-protected-resource`, `/.well-known/oauth-authorization-server`, `/.well-known/openid-configuration`). If `/.well-known/oauth-authorization-server` returns `200 OK`, OpenAI locks the server into `Authentication: OAuth` (`Authorization unavailable`) and aborts the tool scan with `The latest scan did not complete. Try rescanning.`.
   - **Return `HTTP 202 Accepted` (empty body) on JSON-RPC notifications (`notifications/initialized`) in `POST /mcp`**: Streamable HTTP MCP clients expect `202 Accepted` rather than `200 OK` with `"id": null`.
   - **Require explicit `"required"` arrays in `inputSchema` & pure stateless computation descriptions**: When `readOnlyHint: true`, avoid `*_base64` binary upload parameters or server-side file-persistence wording so OpenAI's automated tool classifier passes with 0 findings.
   - **Final `Submit for review` Modal (`Additional Submission Context`)**: Check all 6 policy attestation checkboxes and include a concise reviewer justification note explaining why all tools use `readOnlyHint=true`, `destructiveHint=false`, `openWorldHint=false` and confirming that no login or test credentials are required (`auth.type: "none"`).
