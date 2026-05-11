"""
Streamlit frontend for the Resume Screening Crew.

Talks to the FastAPI backend (researcher.api). Configure via API_URL env var;
defaults to http://localhost:8000.

Run with:
    streamlit run streamlit_app.py
"""

import os
import time

import requests
import streamlit as st

API_URL = os.environ.get("API_URL", "http://localhost:8000")
POLL_INTERVAL_SEC = 2.0

DEFAULT_JD = (
    "Senior Data Scientist with 5+ years of experience in Python, "
    "machine learning, and NLP. Must have worked on production ML systems."
)


# ---------- API client helpers ----------

def api_get(path: str, **kwargs) -> dict:
    r = requests.get(f"{API_URL}{path}", timeout=10, **kwargs)
    r.raise_for_status()
    return r.json()


def api_post(path: str, **kwargs) -> dict:
    r = requests.post(f"{API_URL}{path}", timeout=30, **kwargs)
    r.raise_for_status()
    return r.json()


def api_delete(path: str, **kwargs) -> dict:
    r = requests.delete(f"{API_URL}{path}", timeout=10, **kwargs)
    r.raise_for_status()
    return r.json()


def check_backend() -> dict | None:
    try:
        return api_get("/health")
    except Exception:
        return None


def flatten_result(r: dict) -> dict:
    return {
        "Candidate": r.get("candidate_id"),
        "Score": r.get("score"),
        "Email type": r.get("email_type"),
        "Email status": r.get("email_status"),
        "Subject": r.get("email_subject"),
        "Sent to": r.get("email_to"),
        "Error": r.get("error"),
    }


# ---------- Page setup ----------

st.set_page_config(page_title="Resume Screening Crew", page_icon="📄", layout="wide")
st.title("📄 Resume Screening Crew")
st.caption("Frontend: Streamlit · Backend: FastAPI · Engine: CrewAI")


# ---------- Session state ----------

if "current_job_id" not in st.session_state:
    st.session_state.current_job_id = None
if "last_results" not in st.session_state:
    st.session_state.last_results = []


# ---------- Sidebar ----------

with st.sidebar:
    st.header("⚙️ Backend")
    st.text_input("API URL", value=API_URL, disabled=True)

    health = check_backend()
    if health:
        st.success("Backend reachable")
        st.write(f"📁 `{health['knowledge_dir']}`")
        if health["gmail_configured"]:
            st.success("Gmail configured")
        else:
            st.warning("Gmail env vars not set")
        st.caption(f"Active jobs: {health['active_jobs']}")
    else:
        st.error(f"Cannot reach backend at {API_URL}")
        st.stop()

    st.divider()
    if st.button("🗑️ Clear ALL resumes & profiles", type="secondary"):
        result = api_delete("/resumes")
        st.success(
            f"Deleted {result['pdfs_deleted']} PDF(s) and "
            f"{len(result['profile_files_deleted'])} profile file(s)."
        )
        st.rerun()


# ---------- 1. Job description ----------

st.subheader("1️⃣ Job description")
job_description = st.text_area(
    "What role are you screening for?",
    value=DEFAULT_JD,
    height=120,
    label_visibility="collapsed",
)


# ---------- 2. Resume management ----------

st.subheader("2️⃣ Resumes")

upload_col, list_col = st.columns([1, 1])

with upload_col:
    st.markdown("**Upload**")
    uploaded = st.file_uploader(
        "Drop PDFs here",
        type=["pdf"],
        accept_multiple_files=True,
        label_visibility="collapsed",
    )

    if st.button("💾 Upload to backend", disabled=not uploaded, use_container_width=True):
        files = [("files", (f.name, f.getvalue(), "application/pdf")) for f in uploaded]
        result = api_post("/resumes", files=files)
        st.success(f"Saved {len(result['saved'])} file(s).")
        if result["skipped"]:
            st.warning(f"Skipped non-PDFs: {result['skipped']}")
        st.rerun()

with list_col:
    st.markdown("**Currently on backend**")
    listing = api_get("/resumes")
    existing = listing.get("resumes", [])

    if not existing:
        st.info("No resumes uploaded yet.")
    else:
        # One row per resume: filename + Remove button.
        for name in existing:
            row_a, row_b = st.columns([4, 1])
            with row_a:
                st.write(f"📄 {name}")
            with row_b:
                # Unique key per resume so Streamlit doesn't conflate the buttons.
                if st.button("Remove", key=f"rm_{name}", use_container_width=True):
                    result = api_delete(f"/resumes/{name}")
                    msg = f"Removed {result['filename']}"
                    if result["profile_files_deleted"]:
                        msg += (
                            f" (and {len(result['profile_files_deleted'])} profile file(s))"
                        )
                    st.success(msg)
                    st.rerun()


# ---------- 3. Run screening ----------

st.subheader("3️⃣ Run screening")

cfg_col1, cfg_col2 = st.columns([1, 1])
with cfg_col1:
    interview_offset = st.number_input(
        "Interview date offset (days from today)",
        min_value=0,
        max_value=60,
        value=5,
    )
with cfg_col2:
    dry_run = st.checkbox(
        "🧪 Dry run (don't actually send emails)",
        value=True,
        help="Sets DRY_RUN=1 on the backend so send_email skips SMTP and just logs.",
    )

job_in_progress = st.session_state.current_job_id is not None
run_disabled = job_in_progress or not existing or not job_description.strip()

if st.button(
    "🚀 Run screening on all resumes",
    type="primary",
    disabled=run_disabled,
    use_container_width=True,
):
    payload = {
        "job_description": job_description,
        "interview_days_offset": int(interview_offset),
        "dry_run": dry_run,
    }
    job = api_post("/jobs", json=payload)
    st.session_state.current_job_id = job["job_id"]
    st.session_state.last_results = []
    st.rerun()


# ---------- Live job progress ----------

if st.session_state.current_job_id:
    job_id = st.session_state.current_job_id
    st.divider()
    st.subheader(f"⏳ Job {job_id}")

    progress_bar = st.progress(0.0)
    status_text = st.empty()
    results_placeholder = st.empty()

    while True:
        try:
            job = api_get(f"/jobs/{job_id}")
        except Exception as e:
            st.error(f"Error polling job: {e}")
            st.session_state.current_job_id = None
            break

        total = max(job["total"], 1)
        completed = job["completed"]
        progress_bar.progress(completed / total)

        if job["status"] == "running":
            status_text.info(
                f"Processing {job.get('current_resume') or '...'} ({completed}/{total})"
            )
        elif job["status"] == "queued":
            status_text.info("Queued, starting up...")
        elif job["status"] == "done":
            status_text.success(f"✅ Done. Processed {total} resume(s).")
            st.session_state.last_results = job["results"]
            st.session_state.current_job_id = None
            break
        elif job["status"] == "error":
            status_text.error(f"❌ Job failed: {job.get('error')}")
            st.session_state.last_results = job["results"]
            st.session_state.current_job_id = None
            break

        # Show partial results as they stream in.
        if job["results"]:
            with results_placeholder.container():
                st.dataframe(
                    [flatten_result(r) for r in job["results"]],
                    use_container_width=True,
                )

        time.sleep(POLL_INTERVAL_SEC)

    st.rerun()


# ---------- Final results ----------

if st.session_state.last_results:
    st.divider()
    st.subheader("📊 Latest results")
    st.dataframe(
        [flatten_result(r) for r in st.session_state.last_results],
        use_container_width=True,
    )
    with st.expander("🔎 Raw results JSON"):
        st.json(st.session_state.last_results)