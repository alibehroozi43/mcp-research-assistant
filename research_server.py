import json
import sqlite3
from pathlib import Path
from typing import Optional

import arxiv

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("research-assistant")


# ---------------------------------------------------------
# Database setup
# ---------------------------------------------------------

DB_PATH = Path(__file__).resolve().with_name(
    "research_library.db"
)


def get_db_connection():
    return sqlite3.connect(DB_PATH)


def initialize_database():

    with get_db_connection() as connection:

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS papers (
                paper_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                authors TEXT,
                summary TEXT,
                pdf_url TEXT,
                published TEXT,
                status TEXT DEFAULT 'unread',
                note TEXT DEFAULT '',
                saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


initialize_database()


# ---------------------------------------------------------
# Helper function
# ---------------------------------------------------------

def fetch_paper_from_arxiv(paper_id: str):

    client = arxiv.Client()

    search = arxiv.Search(
        id_list=[paper_id]
    )

    results = list(
        client.results(search)
    )

    if not results:
        return None

    return results[0]


# ---------------------------------------------------------
# MCP Tool 1
# Search
# ---------------------------------------------------------

@mcp.tool()
def search_arxiv(
    query: str,
    max_results: int = 5
) -> list[dict]:

    """Search arXiv for research papers."""

    client = arxiv.Client()

    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.Relevance
    )

    papers = []

    for paper in client.results(search):

        papers.append(
            {
                "paper_id": paper.get_short_id(),
                "title": paper.title,
                "authors": [
                    author.name
                    for author in paper.authors
                ],
                "published": str(
                    paper.published.date()
                ),
                "pdf_url": paper.pdf_url
            }
        )

    return papers


# ---------------------------------------------------------
# MCP Tool 2
# Paper details
# ---------------------------------------------------------

@mcp.tool()
def get_paper_details(
    paper_id: str
) -> dict:

    """Get detailed information for one arXiv paper."""

    paper = fetch_paper_from_arxiv(
        paper_id
    )

    if paper is None:

        return {
            "error": "Paper not found"
        }

    return {
        "paper_id": paper.get_short_id(),
        "title": paper.title,
        "authors": [
            author.name
            for author in paper.authors
        ],
        "summary": paper.summary,
        "published": str(
            paper.published.date()
        ),
        "pdf_url": paper.pdf_url
    }


# ---------------------------------------------------------
# MCP Tool 3
# Save paper
# ---------------------------------------------------------

@mcp.tool()
def save_paper(
    paper_id: str,
    status: str = "unread"
) -> dict:

    """Save an arXiv paper to the reading list."""

    allowed_statuses = {
        "unread",
        "reading",
        "read"
    }

    if status not in allowed_statuses:

        return {
            "error": (
                "Status must be unread, "
                "reading, or read."
            )
        }

    paper = fetch_paper_from_arxiv(
        paper_id
    )

    if paper is None:

        return {
            "error": "Paper not found"
        }

    authors = [
        author.name
        for author in paper.authors
    ]

    with get_db_connection() as connection:

        connection.execute(
            """
            INSERT INTO papers (
                paper_id,
                title,
                authors,
                summary,
                pdf_url,
                published,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)

            ON CONFLICT(paper_id)
            DO UPDATE SET
                title = excluded.title,
                authors = excluded.authors,
                summary = excluded.summary,
                pdf_url = excluded.pdf_url,
                published = excluded.published
            """,
            (
                paper.get_short_id(),
                paper.title,
                json.dumps(authors),
                paper.summary,
                paper.pdf_url,
                str(paper.published.date()),
                status
            )
        )

    with get_db_connection() as connection:
        current_status = connection.execute(
            "SELECT status FROM papers WHERE paper_id = ?",
            (paper.get_short_id(),)
        ).fetchone()[0]

    return {
        "message": "Paper saved successfully",
        "paper_id": paper.get_short_id(),
        "title": paper.title,
        "status": current_status
    }


@mcp.tool()
def list_saved_papers(
    status: Optional[str] = None
) -> list[dict]:

    """List papers saved in the reading list."""

    with get_db_connection() as connection:
        connection.row_factory = sqlite3.Row

        if status:
            rows = connection.execute(
                """
                SELECT *
                FROM papers
                WHERE status = ?
                ORDER BY saved_at DESC
                """,
                (status,)
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT *
                FROM papers
                ORDER BY saved_at DESC
                """
            ).fetchall()

    papers = []

    for row in rows:
        papers.append(
            {
                "paper_id": row["paper_id"],
                "title": row["title"],
                "authors": json.loads(row["authors"]),
                "published": row["published"],
                "status": row["status"],
                "note": row["note"],
                "pdf_url": row["pdf_url"]
            }
        )

    return papers


@mcp.tool()
def update_paper_status(
    paper_id: str,
    status: str
) -> dict:

    """Update reading status of a saved paper."""

    allowed_statuses = {
        "unread",
        "reading",
        "read"
    }

    if status not in allowed_statuses:
        return {
            "error": "Status must be unread, reading, or read."
        }

    with get_db_connection() as connection:

        cursor = connection.execute(
            """
            UPDATE papers
            SET status = ?
            WHERE paper_id = ?
            """,
            (status, paper_id)
        )

    if cursor.rowcount == 0:
        return {
            "error": "Paper is not saved in the reading list."
        }

    return {
        "message": "Status updated",
        "paper_id": paper_id,
        "status": status
    }


@mcp.tool()
def add_note(
    paper_id: str,
    note: str
) -> dict:

    """Add or replace a note for a saved paper."""

    with get_db_connection() as connection:

        cursor = connection.execute(
            """
            UPDATE papers
            SET note = ?
            WHERE paper_id = ?
            """,
            (note, paper_id)
        )

    if cursor.rowcount == 0:
        return {
            "error": "Paper is not saved in the reading list."
        }

    return {
        "message": "Note saved",
        "paper_id": paper_id,
        "note": note
    }


# ---------------------------------------------------------
# Start server
# ---------------------------------------------------------

if __name__ == "__main__":

    mcp.run(
        transport="stdio"
    )
