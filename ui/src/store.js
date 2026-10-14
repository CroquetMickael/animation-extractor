import { create } from 'zustand';
import { api, decodeFloats } from './api.js';

export const FULL = '__full__';
let motionToken = 0;
const HISTORY_LIMIT = 100;

export const useStore = create((set, get) => ({
  system: null,
  projectId: null,
  project: null,
  clipId: null,
  focusClipId: null,
  history: [],
  future: [],
  motion: null,
  motionLoading: false,
  motionError: null,
  frame: 0,
  playing: false,
  selectedBone: null,
  edits: { calibration: {}, keys: {} },
  editMode: 'key',
  keyRadius: 12,
  showOverlay: true,
  showVideo: true,
  inspectorTab: 'clip',
  job: null,

  loadSystem: async () => set({ system: await api.system() }),

  openProject: async (projectId) => {
    const project = await api.project(projectId);
    const edits = await api.edits(projectId);
    const first = project.clips[0]?.id ?? null;
    set({ projectId, project, edits, clipId: first, focusClipId: first, frame: 0, motion: null, selectedBone: null, history: [], future: [] });
    await get().reloadMotion();
  },

  closeProject: () => set({ projectId: null, project: null, motion: null, clipId: null, playing: false }),

  refreshProject: async () => {
    const { projectId } = get();
    if (!projectId) return;
    set({ project: await api.project(projectId) });
  },

  // Undo history: every user change snapshots what it is about to overwrite (clips, settings, dictionary
  // name and bone edits), so Ctrl+Z can put both the project file and edits.json back as they were.
  snapshot: () => {
    const { project, edits } = get();
    return {
      project: { clips: structuredClone(project.clips), settings: { ...project.settings }, dict_name: project.dict_name },
      edits: structuredClone(edits),
    };
  },

  record: () => set((s) => ({ history: [...s.history, get().snapshot()].slice(-HISTORY_LIMIT), future: [] })),

  restore: async (state) => {
    const { projectId, clipId } = get();
    const project = await api.updateProject(projectId, state.project);
    await api.saveEdits(projectId, state.edits);
    set({ project, edits: state.edits, selectedBone: null });
    if (clipId !== FULL && !project.clips.some((c) => c.id === clipId)) {
      await get().selectClip(project.clips[0]?.id ?? FULL);
      return;
    }
    await get().reloadMotion();
  },

  undo: async () => {
    const { history } = get();
    if (!history.length) return;
    const previous = history[history.length - 1];
    set((s) => ({ history: s.history.slice(0, -1), future: [...s.future, get().snapshot()], playing: false }));
    await get().restore(previous);
  },

  redo: async () => {
    const { future } = get();
    if (!future.length) return;
    const next = future[future.length - 1];
    set((s) => ({ future: s.future.slice(0, -1), history: [...s.history, get().snapshot()], playing: false }));
    await get().restore(next);
  },

  patchProject: async (patch) => {
    const { projectId } = get();
    get().record();
    const project = await api.updateProject(projectId, patch);
    set({ project });
    await get().reloadMotion();
  },

  updateClip: async (clipId, changes) => {
    const { project } = get();
    const clips = project.clips.map((c) => (c.id === clipId ? { ...c, ...changes } : c));
    await get().patchProject({ clips });
  },

  selectClip: async (clipId, frame = 0) => {
    if (clipId !== FULL) set({ focusClipId: clipId });
    set({ clipId, frame, playing: false, selectedBone: clipId === FULL ? null : get().selectedBone });
    await get().reloadMotion();
  },

  // Absolute video frame under the playhead, whatever the mode.
  sourceFrame: () => {
    const { clipId, frame, project } = get();
    if (clipId === FULL || !project) return frame;
    const clip = project.clips.find((c) => c.id === clipId);
    return clip ? clip.start + frame * (clip.speed || 1) : frame;
  },

  // Clip the cutting tools act on: the one being edited, else the one under the playhead.
  targetClip: () => {
    const { clipId, project, focusClipId } = get();
    if (!project) return null;
    if (clipId !== FULL) return project.clips.find((c) => c.id === clipId) || null;
    const at = get().sourceFrame();
    return project.clips.find((c) => at >= c.start && at <= c.end) || project.clips.find((c) => c.id === focusClipId) || null;
  },

  seekSource: async (source) => {
    const { clipId } = get();
    if (clipId !== FULL) await get().selectClip(FULL, source);
    else get().setFrame(source);
  },

  splitAtPlayhead: async () => {
    const { projectId } = get();
    const clip = get().targetClip();
    const at = Math.round(get().sourceFrame());
    if (!clip) return 'Aucun clip sous la tête de lecture.';
    try {
      get().record();
      const result = await api.splitClip(projectId, clip.id, at);
      set({ project: result.project });
      await get().reloadMotion();
      return null;
    } catch (e) {
      return e.message;
    }
  },

  setClipBound: async (edge) => {
    const clip = get().targetClip();
    if (!clip) return 'Aucun clip sélectionné.';
    const at = Math.round(get().sourceFrame());
    if (edge === 'start' && at >= clip.end - 1) return 'Le début doit précéder la fin.';
    if (edge === 'end' && at <= clip.start + 1) return 'La fin doit suivre le début.';
    await get().updateClip(clip.id, { [edge]: at });
    return null;
  },

  newClipAtPlayhead: async () => {
    const { project } = get();
    const at = Math.round(get().sourceFrame());
    const nextStart = project.clips.filter((c) => c.start > at).reduce((min, c) => Math.min(min, c.start), project.frames - 1);
    const end = Math.min(nextStart, at + Math.round(project.fps * 3), project.frames - 1);
    if (end - at < 2) return 'Pas assez de place ici pour un nouveau clip.';
    const clips = [...project.clips, { name: `anim_${String(project.clips.length + 1).padStart(2, '0')}`, start: at, end }];
    await get().patchProject({ clips });
    const created = get().project.clips.find((c) => c.start === at);
    if (created) set({ focusClipId: created.id });
    return null;
  },

  mergeNext: async (clipId) => {
    const { projectId } = get();
    try {
      get().record();
      const result = await api.mergeNext(projectId, clipId);
      set({ project: result.project });
      await get().reloadMotion();
      return null;
    } catch (e) {
      return e.message;
    }
  },

  applyCuts: async (cuts, replace) => {
    const { project } = get();
    const bounds = [0, ...cuts, project.frames - 1];
    const generated = bounds.slice(0, -1).map((start, i) => ({
      name: `anim_${String(i + 1).padStart(2, '0')}`,
      start,
      end: bounds[i + 1],
    }));
    const clips = replace ? generated : [...project.clips, ...generated];
    await get().patchProject({ clips });
    await get().selectClip(FULL, get().frame);
  },

  reloadMotion: async () => {
    const { projectId, clipId, project } = get();
    if (!projectId || !clipId || !project) return;
    const hasCapture = project.captures?.[project.settings.engine];
    if (!hasCapture) {
      set({ motion: null, motionError: null });
      return;
    }
    const token = ++motionToken;
    set({ motionLoading: true, motionError: null });
    try {
      const data = await api.motion(projectId, clipId);
      if (token !== motionToken) return;
      const motion = {
        fps: data.fps,
        frames: data.frames,
        bones: data.bones,
        rotations: decodeFloats(data.rotations),
        root: decodeFloats(data.root),
        travel: data.travel,
        mover: data.mover && {
          translation: decodeFloats(data.mover.translation),
          rotation: decodeFloats(data.mover.rotation),
        },
        camera: data.camera && {
          offset: decodeFloats(data.camera.offset),
          forward: decodeFloats(data.camera.forward),
          up: decodeFloats(data.camera.up),
          fov: data.camera.fov,
        },
      };
      set((state) => ({ motion, motionLoading: false, frame: Math.min(state.frame, motion.frames - 1) }));
    } catch (error) {
      if (token !== motionToken) return;
      set({ motion: null, motionLoading: false, motionError: error.message });
    }
  },

  setFrame: (frame) => {
    const { motion } = get();
    if (!motion) return;
    set({ frame: Math.max(0, Math.min(motion.frames - 1, Math.round(frame))) });
  },

  setPlaying: (playing) => set({ playing }),
  selectBone: (selectedBone) => set({ selectedBone }),
  setEditMode: (editMode) => set({ editMode }),
  setKeyRadius: (keyRadius) => set({ keyRadius }),
  toggleOverlay: () => set((s) => ({ showOverlay: !s.showOverlay })),
  setShowVideo: (showVideo) => set({ showVideo }),
  setInspectorTab: (inspectorTab) => set({ inspectorTab }),

  saveEdits: async (edits) => {
    const { projectId } = get();
    get().record();
    set({ edits });
    await api.saveEdits(projectId, edits);
    await get().reloadMotion();
  },

  addBoneOffset: async (bone, offset) => {
    const { edits, editMode, clipId, frame, keyRadius } = get();
    const next = structuredClone(edits);
    if (editMode === 'calibration') {
      const previous = next.calibration[bone];
      next.calibration[bone] = previous ? multiply(previous, offset) : offset;
    } else {
      next.keys[clipId] = [...(next.keys[clipId] || []), { bone, frame, q: offset, radius: keyRadius }];
    }
    await get().saveEdits(next);
  },

  removeKey: async (index) => {
    const { edits, clipId } = get();
    const next = structuredClone(edits);
    next.keys[clipId] = (next.keys[clipId] || []).filter((_, i) => i !== index);
    await get().saveEdits(next);
  },

  clearCalibration: async (bone) => {
    const { edits } = get();
    const next = structuredClone(edits);
    if (bone) delete next.calibration[bone];
    else next.calibration = {};
    await get().saveEdits(next);
  },

  setJob: (job) => set({ job }),
}));

function multiply(a, b) {
  const [ax, ay, az, aw] = a;
  const [bx, by, bz, bw] = b;
  return [
    aw * bx + ax * bw + ay * bz - az * by,
    aw * by - ax * bz + ay * bw + az * bx,
    aw * bz + ax * by - ay * bx + az * bw,
    aw * bw - ax * bx - ay * by - az * bz,
  ];
}
