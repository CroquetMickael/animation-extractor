import { useStore } from '../store.js';
import ClipTab from './tabs/ClipTab.jsx';
import BonesTab from './tabs/BonesTab.jsx';
import SettingsTab from './tabs/SettingsTab.jsx';
import ExportTab from './tabs/ExportTab.jsx';
import MovesetTab from './tabs/MovesetTab.jsx';

const TABS = [
  ['clip', 'Clips', ClipTab],
  ['bones', 'Os', BonesTab],
  ['settings', 'Réglages', SettingsTab],
  ['moveset', 'Démarches', MovesetTab],
  ['export', 'Export', ExportTab],
];

export default function Inspector() {
  const tab = useStore((s) => s.inspectorTab);
  const setTab = useStore((s) => s.setInspectorTab);
  const Active = (TABS.find(([id]) => id === tab) || TABS[0])[2];
  return (
    <aside className="inspector">
      <nav className="tabs">
        {TABS.map(([id, label]) => (
          <button key={id} className={id === tab ? 'active' : ''} onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
      </nav>
      <div className="tab-body">
        <Active />
      </div>
    </aside>
  );
}
