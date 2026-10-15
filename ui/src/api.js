async function request(path, options = {}) {
  const response = await fetch(`/api${path}`, options);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // body was not JSON
    }
    throw new Error(detail);
  }
  return response.json();
}

const json = (method, body) => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

export const api = {
  system: () => request('/system'),
  projects: () => request('/projects'),
  project: (id) => request(`/projects/${id}`),
  createProject: (file, name) => {
    const form = new FormData();
    form.append('video', file);
    form.append('name', name);
    return request('/projects', { method: 'POST', body: form });
  },
  updateProject: (id, patch) => request(`/projects/${id}`, json('PUT', patch)),
  deleteProject: (id) => request(`/projects/${id}`, { method: 'DELETE' }),
  capture: (id, engine) => request(`/projects/${id}/capture?engine=${engine}`, { method: 'POST' }),
  job: (id) => request(`/jobs/${id}`),
  motion: (id, clip) => request(`/projects/${id}/motion?clip=${clip}`),
  overlay: (id) => request(`/projects/${id}/overlay`),
  edits: (id) => request(`/projects/${id}/edits`),
  saveEdits: (id, edits) => request(`/projects/${id}/edits`, json('PUT', edits)),
  exportProject: (id) => request(`/projects/${id}/export`, { method: 'POST' }),
  splitClip: (id, clipId, at) => request(`/projects/${id}/clips/${clipId}/split?at=${Math.round(at)}`, { method: 'POST' }),
  mergeNext: (id, clipId) => request(`/projects/${id}/clips/${clipId}/merge-next`, { method: 'POST' }),
  cutCandidates: (id) => request(`/projects/${id}/cut-candidates`),
  suggestMoveset: (id) => request(`/projects/${id}/moveset/suggest`),
  exportMoveset: (id, movesetId) => request(`/projects/${id}/movesets/${movesetId}/export`, { method: 'POST' }),
  movesetPreviewClips: (id, movesetId) => request(`/projects/${id}/movesets/${movesetId}/preview-clips`),
  movesetPreview: (id, movesetId, clip) => request(`/projects/${id}/movesets/${movesetId}/preview?clip=${encodeURIComponent(clip)}`),
  installMoveset: (id, movesetId, resourcesDir) => request(`/projects/${id}/movesets/${movesetId}/install`, json('POST', { resources_dir: resourcesDir })),
  install: (id, streamDir) => request(`/projects/${id}/install`, json('POST', { stream_dir: streamDir })),
  videoUrl: (id) => `/api/projects/${id}/video`,
  downloadUrl: (id) => `/api/projects/${id}/download`,
  movesetDownloadUrl: (id, movesetId) => `/api/projects/${id}/movesets/${movesetId}/download`,
};

export function decodeFloats(base64) {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new Float32Array(bytes.buffer);
}

export async function waitForJob(jobId, onProgress) {
  for (;;) {
    const job = await api.job(jobId);
    onProgress?.(job);
    if (job.state === 'done') return job;
    if (job.state === 'error') throw new Error(job.error || 'job failed');
    await new Promise((resolve) => setTimeout(resolve, 700));
  }
}
