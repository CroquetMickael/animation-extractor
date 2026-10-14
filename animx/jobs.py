"""Background jobs (captures, exports) with progress the editor polls."""
import threading
import time
import traceback
import uuid

_jobs = {}


def start(kind, project_id, fn):
    # One job per project at a time: a second click joins the running one instead of racing it.
    for existing in _jobs.values():
        if existing["project"] == project_id and existing["state"] == "running":
            return existing

    job_id = uuid.uuid4().hex[:10]
    job = {"id": job_id, "kind": kind, "project": project_id, "state": "running", "progress": 0.0,
           "message": "", "started": time.time(), "error": None, "result": None}
    _jobs[job_id] = job

    def report(progress=None, message=None):
        if progress is not None:
            job["progress"] = float(max(0.0, min(1.0, progress)))
        if message is not None:
            job["message"] = message

    def run():
        try:
            job["result"] = fn(report)
            job["state"] = "done"
            job["progress"] = 1.0
        except Exception as ex:
            job["state"] = "error"
            job["error"] = f"{ex}\n{traceback.format_exc()}"

    threading.Thread(target=run, daemon=True).start()
    return job


def get(job_id):
    return _jobs.get(job_id)


def for_project(project_id):
    return [j for j in _jobs.values() if j["project"] == project_id]
