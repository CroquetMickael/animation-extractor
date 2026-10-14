import { useEffect, useState } from 'react';

export function CommitInput({ value, onCommit, type = 'text', className = 'text', ...rest }) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const commit = () => {
    const next = type === 'number' ? Number(draft) : draft;
    if (next !== value && !(type === 'number' && Number.isNaN(next))) onCommit(next);
  };
  return (
    <input
      {...rest}
      type={type}
      className={className}
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
    />
  );
}

export function Toggle({ label, checked, onChange, hint }) {
  return (
    <label className="toggle-row" title={hint}>
      <span>{label}</span>
      <input type="checkbox" checked={!!checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="switch" />
    </label>
  );
}

export function Slider({ label, value, min, max, step, onCommit, format = (v) => v }) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  return (
    <label className="slider-row">
      <span>
        {label} <em>{format(Number(draft))}</em>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={draft}
        onChange={(e) => setDraft(Number(e.target.value))}
        onPointerUp={() => draft !== value && onCommit(draft)}
        onKeyUp={() => draft !== value && onCommit(draft)}
      />
    </label>
  );
}
