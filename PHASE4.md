# Phase 4 - vision rescue + row fixes

    python -m bookable.phase3 --from-reports --llm     # rescue only payables that do NOT foot
    $env:ANTHROPIC_API_KEY="..."                       # PowerShell; needs: uv pip install anthropic

Gate: model output is accepted only if erp_book(...) == printed gross. Numbers and ALL master codes are
recomputed locally; model-supplied codes are discarded. Responses are cached in .cache/llm/.
Fixed: position number taken as quantity (INV-01 line 2), space-thousands ("6 976.80"), "1 1 1" noise rows.
Not verified: real API calls (tests use a fake client). Rule-based footing unchanged: 12 of 39.

## Gemini
    uv pip install google-genai
    $env:GEMINI_API_KEY="..."          # never commit it; .env and *.key are already in .gitignore
    python -m bookable.phase3 --from-reports --llm --provider gemini
Default model gemini-2.5-flash; override: $env:BOOKABLE_MODEL="<model name from ai.google.dev>".

## API key in .env (easiest)
Copy `.env.example` to `.env`, put `GEMINI_API_KEY=your-key`, then just run
`python -m bookable.phase3 --from-reports --llm`. `.env` is git-ignored; real environment variables override it.
