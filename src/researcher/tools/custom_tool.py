# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "fastmcp",
#     "httpx",
# ]
# ///

import random
from datetime import datetime
from pathlib import Path

import httpx
from fastmcp import FastMCP

from typing import Type
from pydantic import BaseModel, Field


class GradeScore(BaseModel):
    score: float = Field(..., description="Overall score between 0 to 1")
    grade: str = Field(..., description="Grade such as A, B, or C")


class Criteria(BaseModel):
    skill: float = Field(..., description="Skill score between 0 to 1")
    yof: float = Field(..., description="Years of experience normalized between 0 to 1")
    role_alignment: float = Field(..., description="Alignment score between 0 to 1")


app = FastMCP(name="Demo Server")


# ---------- Tools (actions the LLM can take) ----------

@app.tool
def roll_dice(n_dice: int = 1, sides: int = 6) -> list[int]:
    """Roll n dice with the given number of sides and return the results."""
    if n_dice < 1 or sides < 2:
        raise ValueError("n_dice must be >= 1 and sides must be >= 2")
    return [random.randint(1, sides) for _ in range(n_dice)]


@app.tool
def add_numbers(a: float, b: float) -> float:
    """Add two numbers together."""
    return a + b


@app.tool
def current_time() -> str:
    """Return the current date and time in ISO format."""
    return datetime.now().isoformat()


@app.tool
def word_count(text: str) -> dict[str, int]:
    """Count words, characters, and lines in the given text."""
    return {
        "words": len(text.split()),
        "characters": len(text),
        "lines": len(text.splitlines()) or 1,
    }

@app.tool
def grader(skill: float, yof: float, role_alignment: float) -> str:
        """Calculates a score and assigns a grade (A, B, C)."""
        sc = (0.5 * skill + 0.3 * role_alignment + 0.2 * yof)

        if sc >= 0.8:
            grade = "A"
        elif sc >= 0.6:
            grade = "B"
        else:
            grade = "C"

        result = GradeScore(score=sc, grade=grade)
        return result.json()


@app.tool
async def fetch_url(url: str) -> str:
    """Fetch a URL and return the response text (first 2000 chars)."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text[:2000]


# ---------- Resources (read-only data the LLM can access) ----------

@app.resource("config://server")
def server_config() -> dict:
    """Static information about this server."""
    return {
        "name": "Demo Server",
        "version": "1.0.0",
        "description": "A small example server with dice, math, and web tools.",
    }


@app.resource("file://readme")
def readme() -> str:
    """Return contents of README.md from the working directory, if it exists."""
    path = Path("README.md")
    if not path.exists():
        return "No README.md found in working directory."
    return path.read_text(encoding="utf-8")


# ---------- Prompts (reusable prompt templates) ----------

@app.prompt
def summarize(text: str, style: str = "concise") -> str:
    """Generate a prompt that asks for a summary in the given style."""
    return f"Please summarize the following text in a {style} style:\n\n{text}"


# ---------- Run the server ----------

if __name__ == "__main__":
    app.run()