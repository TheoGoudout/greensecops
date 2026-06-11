package greensecops.energy.artifact_reuse

import rego.v1

# Detects when a job uploads an artifact but downstream jobs (declared via needs:)
# do not download it, meaning the upload is wasted energy.

_uploads_artifact(job) if {
    some step in job.steps
    contains(step.uses, "actions/upload-artifact")
}

_downloads_artifact(job) if {
    some step in job.steps
    contains(step.uses, "actions/download-artifact")
}

_needs_jobs(job) := needs if {
    raw := job.needs
    is_array(raw)
    needs := {n | n := raw[_]}
}

_needs_jobs(job) := needs if {
    raw := job.needs
    is_string(raw)
    needs := {raw}
}

violations contains violation if {
    some uploader_name, uploader in input.jobs
    _uploads_artifact(uploader)

    # Find all jobs that need the uploader
    some downloader_name, downloader in input.jobs
    downloader_name != uploader_name
    needs := _needs_jobs(downloader)
    uploader_name in needs
    not _downloads_artifact(downloader)

    violation := {
        "rule": "artifact_reuse",
        "severity": "medium",
        "category": "energy",
        "job": downloader_name,
        "message": sprintf("Job '%v' depends on '%v' which uploads an artifact, but does not use actions/download-artifact. The upload may be wasted.", [downloader_name, uploader_name]),
        "context": null,
    }
}
