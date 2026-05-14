import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import box
from rich.text import Text

import db
import github_client
import tree_sitter_parser
import analyzer

console = Console()

RISK_COLORS = {
    "low": "green",
    "medium": "yellow",
    "high": "red",
    "critical": "bold red",
}

SEVERITY_COLORS = {
    "info": "cyan",
    "warning": "yellow",
    "error": "red",
}


def _score_bar(score: int) -> str:
    filled = score // 10
    bar = "█" * filled + "░" * (10 - filled)
    color = "green" if score >= 70 else "yellow" if score >= 40 else "red"
    return f"[{color}]{bar}[/{color}] {score}/100"


@click.group()
def cli():
    """Codesense — AI-powered PR review using Claude + Tree-sitter."""
    db.init_db()


@cli.command()
@click.argument("pr_url")
@click.option("--no-save", is_flag=True, default=False, help="Skip saving to SQLite.")
def review(pr_url: str, no_save: bool):
    """Review a GitHub pull request.

    \b
    Example:
        python cli.py review https://github.com/owner/repo/pull/42
    """
    console.rule("[bold blue]Codesense PR Review[/bold blue]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
        console=console,
    ) as progress:
        task = progress.add_task("Fetching PR from GitHub...", total=None)
        try:
            pr = github_client.fetch_pr(pr_url)
        except Exception as e:
            console.print(f"[red]Failed to fetch PR:[/red] {e}")
            raise SystemExit(1)

        progress.update(task, description="Parsing changed files with Tree-sitter...")
        parsed = tree_sitter_parser.parse_changed_files(pr["changed_files"])

        progress.update(task, description="Sending to Claude for analysis...")
        try:
            result = analyzer.analyze_pr(pr, parsed)
        except Exception as e:
            console.print(f"[red]Analysis failed:[/red] {e}")
            raise SystemExit(1)

    # ── Header panel ──────────────────────────────────────────────────────────
    risk = result["risk_level"]
    risk_color = RISK_COLORS.get(risk, "white")
    header = (
        f"[bold]{pr['title']}[/bold]\n"
        f"[dim]{pr['url']}[/dim]\n"
        f"Author: [cyan]{pr['author']}[/cyan]  |  "
        f"Branch: [dim]{pr['head_branch']}[/dim] → [dim]{pr['base_branch']}[/dim]"
    )
    console.print(Panel(header, title="Pull Request", border_style="blue"))

    # ── Scores ────────────────────────────────────────────────────────────────
    console.print()
    console.print(f"  Alignment Score  {_score_bar(result['alignment_score'])}")
    risk_text = Text(f"  Risk Level       [{risk.upper()}]", style=risk_color)
    console.print(risk_text)
    console.print()

    # ── Summary ───────────────────────────────────────────────────────────────
    console.print(Panel(result["summary"], title="Summary", border_style="dim"))

    # ── Mismatches ────────────────────────────────────────────────────────────
    if result.get("mismatches"):
        console.print("\n[bold yellow]Intent Mismatches[/bold yellow]")
        for m in result["mismatches"]:
            console.print(f"  [yellow]⚠[/yellow]  {m}")

    # ── Findings table ────────────────────────────────────────────────────────
    findings = result.get("findings", [])
    if findings:
        console.print()
        table = Table(
            title="Findings",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold",
            expand=True,
        )
        table.add_column("Severity", width=10)
        table.add_column("File", style="dim", no_wrap=False)
        table.add_column("Message", no_wrap=False)

        for f in findings:
            sev = f.get("severity", "info")
            color = SEVERITY_COLORS.get(sev, "white")
            table.add_row(
                f"[{color}]{sev.upper()}[/{color}]",
                f.get("file", "—"),
                f.get("message", ""),
            )
        console.print(table)

    # ── Changed files summary ─────────────────────────────────────────────────
    if pr["changed_files"]:
        console.print()
        file_table = Table(title="Changed Files", box=box.SIMPLE, show_header=True)
        file_table.add_column("File", style="dim")
        file_table.add_column("Status", width=10)
        file_table.add_column("+", style="green", width=6)
        file_table.add_column("-", style="red", width=6)
        for cf in pr["changed_files"]:
            file_table.add_row(
                cf["filename"],
                cf["status"],
                str(cf["additions"]),
                str(cf["deletions"]),
            )
        console.print(file_table)

    # ── Persist ───────────────────────────────────────────────────────────────
    if not no_save:
        review_id = db.save_review(
            pr_url=pr_url,
            pr_title=pr["title"],
            repo=f"{pr['owner']}/{pr['repo']}",
            pr_number=pr["number"],
            alignment=result["alignment_score"],
            risk=result["risk_level"],
            findings=findings,
        )
        console.print(f"\n[dim]Saved to database (id={review_id})[/dim]")

    console.rule()


@cli.command()
@click.option("--limit", default=10, show_default=True, help="Number of reviews to show.")
def history(limit: int):
    """Show recent reviews from the local database."""
    rows = db.get_recent_reviews(limit)
    if not rows:
        console.print("[dim]No reviews yet. Run: python cli.py review <PR-URL>[/dim]")
        return

    table = Table(title="Recent Reviews", box=box.ROUNDED, expand=True)
    table.add_column("ID", width=4)
    table.add_column("PR", no_wrap=False)
    table.add_column("Alignment", width=12)
    table.add_column("Risk", width=10)
    table.add_column("Reviewed At", width=20)

    for r in rows:
        risk = r["risk"] or "—"
        color = RISK_COLORS.get(risk, "white")
        table.add_row(
            str(r["id"]),
            f"[link={r['pr_url']}]{r['pr_title'] or r['pr_url']}[/link]",
            _score_bar(r["alignment"] or 0),
            f"[{color}]{risk.upper()}[/{color}]",
            r["reviewed_at"][:19],
        )

    console.print(table)


if __name__ == "__main__":
    cli()
