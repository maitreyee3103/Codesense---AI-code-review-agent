import os
import anthropic
from dotenv import load_dotenv
from tree_sitter_parser import ParsedFile, summarize_for_prompt

load_dotenv(override=True)

MODEL = "claude-sonnet-4-6"

REVIEW_TOOL = {
    "name": "submit_review",
    "description": (
        "Submit a structured code review after analyzing the PR. "
        "Call this exactly once with your complete findings."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "alignment_score": {
                "type": "integer",
                "minimum": 0,
                "maximum": 100,
                "description": (
                    "How well the code changes match the PR's stated intent. "
                    "100 = perfect match, 0 = completely unrelated."
                ),
            },
            "risk_level": {
                "type": "string",
                "enum": ["low", "medium", "high", "critical"],
                "description": "Overall risk of merging this PR.",
            },
            "summary": {
                "type": "string",
                "description": "2-3 sentence high-level summary of the review.",
            },
            "findings": {
                "type": "array",
                "description": "Specific issues or observations found in the diff.",
                "items": {
                    "type": "object",
                    "properties": {
                        "severity": {
                            "type": "string",
                            "enum": ["info", "warning", "error"],
                        },
                        "file": {"type": "string"},
                        "message": {"type": "string"},
                    },
                    "required": ["severity", "file", "message"],
                },
            },
            "mismatches": {
                "type": "array",
                "description": (
                    "Cases where the code does something different from what the "
                    "PR description claims. Empty list if fully aligned."
                ),
                "items": {"type": "string"},
            },
        },
        "required": ["alignment_score", "risk_level", "summary", "findings", "mismatches"],
    },
}


def _build_prompt(pr: dict, parsed_files: list[ParsedFile]) -> str:
    semantic_summary = summarize_for_prompt(parsed_files)

    # Include actual diff patches for the files (truncated to avoid huge context)
    diff_sections = []
    for f in pr["changed_files"]:
        patch = f.get("patch", "")
        if patch:
            truncated = patch if len(patch) < 3000 else patch[:3000] + "\n... (truncated)"
            diff_sections.append(f"#### {f['filename']} ({f['status']})\n```diff\n{truncated}\n```")

    diffs = "\n\n".join(diff_sections) or "No text diffs available."

    return f"""You are an expert code reviewer. Analyze this GitHub pull request and call the `submit_review` tool with your findings.

## PR Details
- **Title:** {pr['title']}
- **Author:** {pr['author']}
- **Branch:** `{pr['head_branch']}` → `{pr['base_branch']}`
- **Description:**
{pr['description'] or '_(no description provided)_'}

## Semantic Summary (Tree-sitter analysis)
{semantic_summary}

## Raw Diffs
{diffs}

## Your Task
1. Determine how well the code changes align with the PR title and description (alignment score).
2. Identify any bugs, security issues, logic errors, or style problems.
3. Flag any cases where the code does something NOT mentioned in the PR description (mismatches).
4. Assign an overall risk level for merging.

Be specific — reference file names and function names in your findings.
"""


def analyze_pr(pr: dict, parsed_files: list[ParsedFile]) -> dict:
    """Send the PR to Claude and return the structured review result."""
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    prompt = _build_prompt(pr, parsed_files)

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        tools=[REVIEW_TOOL],
        tool_choice={"type": "any"},
        messages=[{"role": "user", "content": prompt}],
    )

    # Extract the tool call result
    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_review":
            return block.input

    raise RuntimeError("Claude did not call submit_review — unexpected response format.")
