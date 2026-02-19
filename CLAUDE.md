# CLAUDE.md — songfly-bot

This file provides guidance for AI assistants (Claude and others) working on the `songfly-bot` project.

---

## Project Overview

**songfly-bot** is a bot project (likely Discord or a similar platform) focused on song and music-related functionality. The repository is currently in its initial state; this document captures intended conventions and structure for development.

> **Note for AI assistants:** This repository was empty at the time this file was created. If source files now exist, update this document to reflect the actual codebase.

---

## Repository State

- **Current status:** Newly initialized, no source files yet
- **Target branch:** `claude/claude-md-mlst8boecl9mydvc-XBfJM`
- **Remote:** `garciadanny334-coder/songfly-bot`

---

## Expected Project Structure

When populated, the project is expected to follow this structure:

```
songfly-bot/
├── CLAUDE.md               # This file
├── README.md               # Human-facing documentation
├── package.json            # Node.js project manifest
├── tsconfig.json           # TypeScript configuration
├── .env.example            # Template for environment variables
├── .gitignore
├── src/
│   ├── index.ts            # Entry point — initializes the bot client
│   ├── config.ts           # Loads and validates environment config
│   ├── commands/           # Bot command handlers (one file per command)
│   │   └── *.ts
│   ├── events/             # Bot event handlers (ready, messageCreate, etc.)
│   │   └── *.ts
│   ├── services/           # Business logic (music search, playback, etc.)
│   │   └── *.ts
│   └── utils/              # Shared helper functions
│       └── *.ts
├── tests/                  # Unit and integration tests
│   └── *.test.ts
└── dist/                   # Compiled output (gitignored)
```

---

## Development Commands

Once `package.json` is set up, the expected script conventions are:

| Command             | Purpose                                    |
|---------------------|--------------------------------------------|
| `npm run dev`       | Start bot in development mode (watch mode) |
| `npm run build`     | Compile TypeScript to `dist/`              |
| `npm start`         | Run compiled bot from `dist/`              |
| `npm test`          | Run test suite                             |
| `npm run lint`      | Lint source files                          |
| `npm run lint:fix`  | Auto-fix lint issues                       |
| `npm run typecheck` | Run TypeScript type-checker without emitting |

---

## Environment Variables

Copy `.env.example` to `.env` before running locally. Expected variables:

```env
# Bot credentials
BOT_TOKEN=          # Discord (or platform) bot token

# Optional: Music/API integrations
YOUTUBE_API_KEY=    # YouTube Data API v3 key (if used)
SPOTIFY_CLIENT_ID=  # Spotify client ID (if used)
SPOTIFY_CLIENT_SECRET=

# Logging
LOG_LEVEL=info      # debug | info | warn | error
```

Never commit `.env` — it is gitignored.

---

## Key Conventions

### Language & Runtime
- **TypeScript** is the primary language. All source files use `.ts`.
- Target Node.js version: `>=18.x` (LTS).
- Strict mode is enabled in `tsconfig.json` (`"strict": true`).

### Code Style
- Formatting enforced by **Prettier** (if configured).
- Linting enforced by **ESLint** with TypeScript rules.
- Prefer `const` over `let`; avoid `var`.
- Use explicit return types on exported functions.
- Async functions should use `async/await`, not raw Promise chains.

### Naming
- Files: `kebab-case.ts`
- Classes: `PascalCase`
- Functions and variables: `camelCase`
- Constants: `UPPER_SNAKE_CASE`
- Command files: named after the command (e.g., `play.ts`, `skip.ts`)

### Imports
- Use absolute imports via `tsconfig` path aliases (e.g., `@/services/music`) when configured.
- Group imports: external packages first, then internal modules, separated by a blank line.

### Error Handling
- Never swallow errors silently. Log them with context before returning or re-throwing.
- User-facing errors (e.g., invalid command usage) should send a friendly message back to the user, not stack traces.

### Commands
- Each command is a self-contained module exporting a `name`, optional `description`, and `execute` function.
- Validate input at the start of `execute` before doing any async work.

### Logging
- Use a structured logger (e.g., `pino` or `winston`). Avoid raw `console.log` in production paths.
- Include contextual metadata (guild ID, user ID, command name) in log entries where relevant.

---

## Testing

- Tests live in `tests/` and mirror the `src/` structure.
- Use **Jest** (or **Vitest**) as the test runner.
- Unit-test pure functions in `utils/` and `services/` in isolation.
- Mock external API calls and the bot client in tests.
- Aim for coverage on business logic; do not test framework internals.

---

## Git Workflow

- **Branch naming:** Feature branches use `claude/<description>-<session-id>` (for AI-generated work) or `feat/<description>` (for human work).
- **Commits:** Write descriptive commit messages in the imperative mood (e.g., `Add play command`, `Fix queue overflow bug`).
- **Do not commit:** `.env`, `dist/`, `node_modules/`, or any credentials.
- **Push:** Always push with `-u` on first push: `git push -u origin <branch-name>`.

---

## Architecture Notes

- The bot client is instantiated once in `src/index.ts` and passed to command/event handlers.
- Commands and events are registered dynamically by loading all files in their respective directories at startup.
- Configuration is centralized in `src/config.ts`, which reads from environment variables and throws at startup if required values are missing.
- External service integrations (music APIs, search providers) are isolated in `src/services/` to keep commands thin.

---

## Adding New Commands

1. Create `src/commands/<command-name>.ts`.
2. Export `name` (string), `description` (string), and `execute(interaction, client)` (async function).
3. The command loader in `src/index.ts` will pick it up automatically on restart.
4. Write a corresponding test in `tests/commands/<command-name>.test.ts`.

---

## Adding New Events

1. Create `src/events/<event-name>.ts`.
2. Export `name` (matching the platform event name) and `execute(...args)`.
3. The event loader registers it automatically.

---

## Security

- Never log or expose the bot token or API keys.
- Validate and sanitize all user-provided input before using it in queries or commands.
- Apply rate limiting on commands where appropriate to prevent abuse.
- Keep dependencies up to date; run `npm audit` periodically.

---

*Last updated: 2026-02-19. Update this file whenever project structure or conventions change significantly.*
