import json
import os
import traceback
from datetime import date, timedelta
from pathlib import Path

from researcher.crew import Researcher  


RESUMES_DIR = Path(
    "D:/machine_learning/test_projects/genai/udemy/crewai/researcher/knowledge"
)

OUTPUT_DIR = Path(
    os.environ.get(
        "OUTPUT_DIR",
        "D:/machine_learning/test_projects/genai/udemy/crewai/researcher/output",
    )
)

JOB_DESCRIPTION = (
    "Senior Data Scientist with 5+ years of experience in Python, "
    "machine learning, and NLP. Must have worked on production ML systems."
)


def _parse_task_output(task_output) -> object:
    """Best-effort parse of a single task's raw output."""
    try:
        return json.loads(task_output.raw)
    except (ValueError, TypeError):
        return task_output.raw


def process_resume(resume_path: Path, inputs: dict) -> None:
    """Run the full crew pipeline for a single resume."""
    print(f"\n{'=' * 60}")
    print(f"Processing: {resume_path.name}")
    print(f"{'=' * 60}")

    researcher = Researcher(resume_path=str(resume_path))
    try:
        result = researcher.crew().kickoff(inputs=inputs)
        print(f"\n--- Result for {resume_path.name} ---")
        print(result)

        research_out, reporting_out, scoring_out, mail_out = result.tasks_output

        consolidated = {
            "candidate_summary": _parse_task_output(research_out),
            "criteria_scores": _parse_task_output(reporting_out),
            "final_score": _parse_task_output(scoring_out),
            "email_result": _parse_task_output(mail_out),
        }

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = OUTPUT_DIR / f"{resume_path.stem}.json"
        out_path.write_text(json.dumps(consolidated, indent=2))
        print(f"✅ Wrote {out_path.resolve()}")

    except Exception as e:
        print(f"❌ Error processing {resume_path.name}: {type(e).__name__}: {e}")
        traceback.print_exc()
    finally:
        researcher.close()


def run() -> None:
    today = date.today()
    interview_date = today + timedelta(days=5)

    inputs = {
        "job_description": JOB_DESCRIPTION,
        "today_date": today.strftime("%A, %B %d, %Y"),
        "interview_date": interview_date.strftime("%A, %B %d, %Y"),
    }

    pdf_files = sorted(RESUMES_DIR.glob("*.pdf"))
    if not pdf_files:
        print(f"No PDF files found in {RESUMES_DIR}")
        return

    print(f"Found {len(pdf_files)} resume(s) to process.")

    for pdf in pdf_files:
        process_resume(pdf, inputs)

    print(f"\n✅ Done. Processed {len(pdf_files)} resume(s).")


if __name__ == "__main__":
    run()