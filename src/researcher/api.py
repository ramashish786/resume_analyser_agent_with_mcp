"""
FastAPI backend for the Resume Screening Crew.

Endpoints:
  GET    /health
  GET    /resumes
  POST   /resumes
  DELETE /resumes/{filename}
  DELETE /resumes
  POST   /jobs
  GET    /jobs/{job_id}

Run with:
    uv run uvicorn researcher.api:app --reload --port 8000
"""

import json
import os
import threading
import traceback
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from researcher.crew import Researcher


# ---------- Configuration ----------

KNOWLEDGE_DIR = Path(
    os.environ.get(
        "RESUMES_DIR",
        "D:/machine_learning/test_projects/genai/udemy/crewai/researcher/knowledge",
    )
)
OUTPUT_DIR = Path(
    os.environ.get(
        "OUTPUT_DIR",
        "D:/machine_learning/test_projects/genai/udemy/crewai/researcher/output",
    )
)


# ---------- App setup ----------

app = FastAPI(title="Resume Screening Crew API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- In-memory job store ----------

JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()


# ---------- Models ----------

class JobCreateRequest(BaseModel):
    job_description: str = Field(..., min_length=1)
    interview_days_offset: int = Field(5, ge=0, le=60)
    dry_run: bool = True


class CandidateResult(BaseModel):
    candidate_id: str
    score: Optional[float] = None
    email_type: Optional[str] = None
    email_status: Optional[str] = None
    email_subject: Optional[str] = None
    email_to: Optional[str] = None
    error: Optional[str] = None


class JobStatus(BaseModel):
    job_id: str
    status: str
    created_at: str
    finished_at: Optional[str] = None
    total: int
    completed: int
    current_resume: Optional[str] = None
    results: list[CandidateResult] = []
    error: Optional[str] = None


class DeleteResumeResponse(BaseModel):
    filename: str
    pdf_deleted: bool
    profile_files_deleted: list[str]


# ---------- Helpers ----------

def _list_resumes() -> list[Path]:
    if not KNOWLEDGE_DIR.exists():
        return []
    return sorted(KNOWLEDGE_DIR.glob("*.pdf"))


def _candidate_artifact_paths(stem: str) -> list[Path]:
    """All output files tied to one candidate. Includes the consolidated format
    AND legacy per-task files so resume removal cleans up everything."""
    return [
        OUTPUT_DIR / f"{stem}.json",             
    ]


def _delete_candidate_profile(stem: str) -> list[str]:
    deleted: list[str] = []
    for p in _candidate_artifact_paths(stem):
        if p.exists():
            try:
                p.unlink()
                deleted.append(p.name)
            except OSError as e:
                deleted.append(f"{p.name} (failed: {e})")
    return deleted


def _safe_json_load(path: Path) -> dict:
    """Load JSON. Strips ```json ... ``` fences if the agent wrapped its output."""
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return {}

    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def _load_candidate_results(candidate_id: str) -> CandidateResult:
    """Read the consolidated {stem}.json. The file structure is:
        {
          "candidate_summary": "...",
          "criteria_scores":   { "skill": 10, "yof": 8, "role_alignment": 9 },
          "final_score":       { "score": 9.1 },
          "email_result":      { "status": "sent", "email_type": "...",
                                 "to": "...", "subject": "...", "score": 9.1 }
        }
    """
    result = CandidateResult(candidate_id=candidate_id)

    data = _safe_json_load(OUTPUT_DIR / f"{candidate_id}.json")
    if not data:
        return result  

    # final_score is a nested object: {"score": 9.1}
    final_score = data.get("final_score")
    if isinstance(final_score, dict):
        result.score = final_score.get("score")

    # email_result is a nested object with all email fields
    email = data.get("email_result")
    if isinstance(email, dict):
        result.email_status = email.get("status")
        result.email_type = email.get("email_type")
        result.email_subject = email.get("subject")
        result.email_to = email.get("to")
        # Fall back to email block if score wasn't readable from final_score
        if result.score is None:
            result.score = email.get("score")

    return result


def _update_job(job_id: str, **fields) -> None:
    with JOBS_LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(fields)


def _safe_filename(filename: str) -> str:
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail=f"Invalid filename: {filename!r}")
    return filename


def _parse_task_output(task_output) -> object:
    try:
        return json.loads(task_output.raw)
    except (ValueError, TypeError):
        return task_output.raw


def _run_screening_job(job_id: str, payload: JobCreateRequest) -> None:
    try:
        os.environ["DRY_RUN"] = "1" if payload.dry_run else "0"

        today = date.today()
        interview_date = today + timedelta(days=payload.interview_days_offset)
        inputs = {
            "job_description": payload.job_description,
            "today_date": today.strftime("%A, %B %d, %Y"),
            "interview_date": interview_date.strftime("%A, %B %d, %Y"),
        }

        resumes = _list_resumes()
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        _update_job(job_id, status="running", total=len(resumes), completed=0)

        for i, resume_path in enumerate(resumes):
            _update_job(job_id, current_resume=resume_path.name)

            try:
                researcher = Researcher(resume_path=str(resume_path))
                try:
                    crew_output = researcher.crew().kickoff(inputs=inputs)
                    research_out, reporting_out, scoring_out, mail_out = (
                        crew_output.tasks_output
                    )

                    consolidated = {
                        "candidate_summary": _parse_task_output(research_out),
                        "criteria_scores": _parse_task_output(reporting_out),
                        "final_score": _parse_task_output(scoring_out),
                        "email_result": _parse_task_output(mail_out),
                    }

                    out_path = OUTPUT_DIR / f"{resume_path.stem}.json"
                    out_path.write_text(
                        json.dumps(consolidated, indent=2), encoding="utf-8"
                    )
                    print(f"[api] wrote {out_path.resolve()}")
                finally:
                    researcher.close()

                result = _load_candidate_results(resume_path.stem)
            except Exception as e:
                traceback.print_exc()
                result = CandidateResult(
                    candidate_id=resume_path.stem,
                    error=f"{type(e).__name__}: {e}",
                )

            with JOBS_LOCK:
                JOBS[job_id]["results"].append(result.model_dump())
                JOBS[job_id]["completed"] = i + 1

        _update_job(
            job_id,
            status="done",
            current_resume=None,
            finished_at=datetime.utcnow().isoformat(),
        )

    except Exception as e:
        traceback.print_exc()
        _update_job(
            job_id,
            status="error",
            error=f"{type(e).__name__}: {e}",
            finished_at=datetime.utcnow().isoformat(),
        )


# ---------- Routes ----------

@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "knowledge_dir": str(KNOWLEDGE_DIR),
        "knowledge_dir_exists": KNOWLEDGE_DIR.exists(),
        "output_dir": str(OUTPUT_DIR),
        "output_dir_exists": OUTPUT_DIR.exists(),
        "gmail_configured": bool(
            os.environ.get("GMAIL_USER") and os.environ.get("GMAIL_APP_PASSWORD")
        ),
        "active_jobs": len(JOBS),
    }


@app.get("/resumes")
def list_resumes() -> dict:
    return {
        "knowledge_dir": str(KNOWLEDGE_DIR),
        "resumes": [p.name for p in _list_resumes()],
    }


@app.post("/resumes")
async def upload_resumes(files: list[UploadFile] = File(...)) -> dict:
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    skipped: list[str] = []

    for f in files:
        if not f.filename or not f.filename.lower().endswith(".pdf"):
            skipped.append(f.filename or "(no name)")
            continue
        safe_name = Path(f.filename).name
        target = KNOWLEDGE_DIR / safe_name
        content = await f.read()
        target.write_bytes(content)
        saved.append(safe_name)

    return {"saved": saved, "skipped": skipped, "knowledge_dir": str(KNOWLEDGE_DIR)}


@app.delete("/resumes/{filename}", response_model=DeleteResumeResponse)
def delete_resume(filename: str) -> DeleteResumeResponse:
    filename = _safe_filename(filename)
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only .pdf files supported")

    pdf_path = KNOWLEDGE_DIR / filename
    pdf_deleted = False
    if pdf_path.exists():
        pdf_path.unlink()
        pdf_deleted = True

    stem = Path(filename).stem
    profile_files_deleted = _delete_candidate_profile(stem)

    if not pdf_deleted and not profile_files_deleted:
        raise HTTPException(status_code=404, detail=f"{filename} not found")

    return DeleteResumeResponse(
        filename=filename,
        pdf_deleted=pdf_deleted,
        profile_files_deleted=profile_files_deleted,
    )


@app.delete("/resumes")
def clear_all_resumes() -> dict:
    pdfs_deleted = 0
    profiles_deleted: list[str] = []

    if KNOWLEDGE_DIR.exists():
        for p in KNOWLEDGE_DIR.glob("*.pdf"):
            stem = p.stem
            p.unlink()
            pdfs_deleted += 1
            profiles_deleted.extend(_delete_candidate_profile(stem))

    return {"pdfs_deleted": pdfs_deleted, "profile_files_deleted": profiles_deleted}


@app.post("/jobs", response_model=JobStatus)
def create_job(payload: JobCreateRequest) -> JobStatus:
    resumes = _list_resumes()
    if not resumes:
        raise HTTPException(
            status_code=400,
            detail=f"No resumes found in {KNOWLEDGE_DIR}. Upload some first.",
        )

    job_id = uuid.uuid4().hex[:12]
    record = {
        "job_id": job_id,
        "status": "queued",
        "created_at": datetime.utcnow().isoformat(),
        "finished_at": None,
        "total": len(resumes),
        "completed": 0,
        "current_resume": None,
        "results": [],
        "error": None,
    }
    with JOBS_LOCK:
        JOBS[job_id] = record

    thread = threading.Thread(
        target=_run_screening_job, args=(job_id, payload), daemon=True
    )
    thread.start()

    return JobStatus(**record)


@app.get("/jobs/{job_id}", response_model=JobStatus)
def get_job(job_id: str) -> JobStatus:
    with JOBS_LOCK:
        record = JOBS.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatus(**record)