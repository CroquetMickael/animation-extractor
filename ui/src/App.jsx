import { useEffect } from 'react';
import { useStore } from './store.js';
import Home from './home/Home.jsx';
import Editor from './editor/Editor.jsx';

export default function App() {
  const projectId = useStore((s) => s.projectId);
  const loadSystem = useStore((s) => s.loadSystem);

  useEffect(() => {
    loadSystem();
  }, [loadSystem]);

  return projectId ? <Editor /> : <Home />;
}
