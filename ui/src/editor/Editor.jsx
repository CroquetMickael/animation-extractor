import { useEffect, useRef } from 'react';
import { useStore } from '../store.js';
import Viewport from './Viewport.jsx';
import VideoPanel from './VideoPanel.jsx';
import Timeline from './Timeline.jsx';
import Inspector from './Inspector.jsx';
import TopBar from './TopBar.jsx';
import CaptureGate from './CaptureGate.jsx';

export default function Editor() {
  usePlayback();
  useShortcuts();
  const project = useStore((s) => s.project);
  if (!project) return null;
  const engine = project.settings.engine;
  const captured = project.captures[engine];

  return (
    <div className="editor">
      <TopBar />
      <div className="editor-body">
        <main className="stage">
          <Viewport />
          <VideoPanel />
          {!captured && <CaptureGate />}
        </main>
        <Inspector />
      </div>
      <Timeline />
    </div>
  );
}

function usePlayback() {
  const playing = useStore((s) => s.playing);
  const last = useRef(0);
  const accumulator = useRef(0);

  useEffect(() => {
    if (!playing) return undefined;
    let raf = 0;
    last.current = performance.now();
    accumulator.current = useStore.getState().frame;
    const tick = (now) => {
      const { motion, setFrame } = useStore.getState();
      if (motion) {
        const dt = (now - last.current) / 1000;
        accumulator.current = (accumulator.current + dt * motion.fps) % motion.frames;
        setFrame(Math.floor(accumulator.current));
      }
      last.current = now;
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing]);
}

function useShortcuts() {
  useEffect(() => {
    const onKey = (event) => {
      if (event.target.closest('input, textarea, select')) return;
      const { frame, setFrame, playing, setPlaying, selectBone, undo, redo } = useStore.getState();
      if ((event.ctrlKey || event.metaKey) && !event.altKey) {
        const key = event.key.toLowerCase();
        if (key === 'z' && !event.shiftKey) {
          event.preventDefault();
          undo();
        } else if (key === 'y' || (key === 'z' && event.shiftKey)) {
          event.preventDefault();
          redo();
        }
        return;
      }
      if (event.code === 'Space') {
        event.preventDefault();
        setPlaying(!playing);
      } else if (event.code === 'ArrowRight') {
        setPlaying(false);
        setFrame(frame + (event.shiftKey ? 10 : 1));
      } else if (event.code === 'ArrowLeft') {
        setPlaying(false);
        setFrame(frame - (event.shiftKey ? 10 : 1));
      } else if (event.code === 'Escape') {
        selectBone(null);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
}
