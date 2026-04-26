# Widget Layout Patterns

Reusable JSX snippets for common widget UI needs.

---

## Loading State
```tsx
<div className="h-full w-full flex items-center justify-center font-mono text-xs text-white/50">
  Loading...
</div>
```

## Error State
```tsx
<div className="h-full w-full flex items-center justify-center font-mono text-xs text-terminal-red/70 p-4 text-center">
  [ERROR] {message}
</div>
```

## Empty State
```tsx
<div className="h-full w-full flex items-center justify-center font-mono text-xs text-white/30">
  No data available.
</div>
```

---

## Section Header Bar
```tsx
<div className="text-terminal-green font-bold uppercase text-[10px] tracking-widest mb-1 px-2">
  Section Title
</div>
```

---

## Scrollable Data Table
```tsx
<div className="h-full w-full flex flex-col font-mono text-xs overflow-auto bg-terminal-bg p-2">
  <div className="overflow-x-auto">
    <table className="w-full text-left border-collapse min-w-[400px]">
      <thead className="text-terminal-amber/60 text-[9px] font-bold uppercase sticky top-0 bg-terminal-bg">
        <tr>
          <th className="pb-1">SYMBOL</th>
          <th className="pb-1 text-right">PRICE</th>
          <th className="pb-1 text-right">CHG%</th>
        </tr>
      </thead>
      <tbody className="text-terminal-amber text-[10px]">
        {rows.map((row) => (
          <tr
            key={row.id}
            className="border-b border-terminal-gray/30 hover:bg-zinc-900 cursor-pointer"
            onClick={() => handleRowClick(row)}
          >
            <td className="py-0.5">{row.symbol}</td>
            <td className="py-0.5 text-right">{row.price}</td>
            <td className="py-0.5 text-right">{formatChange(row.pChange)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  </div>
</div>
```

---

## Color-Coded Change Cell
```tsx
function formatChange(val: number | null | undefined): React.ReactNode {
  if (val == null || isNaN(val)) return <span className="text-white/50">—</span>;
  const isUp = val > 0;
  return (
    <span className={isUp ? 'text-terminal-green font-bold' : 'text-terminal-red font-bold'}>
      {isUp ? '+' : ''}{val.toFixed(2)}%
    </span>
  );
}
```

---

## Tab Bar
```tsx
type Tab = 'global' | 'company';

function TabButton({ active, onClick, label }: { active: boolean; onClick: () => void; label: string }) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1 text-[10px] font-mono uppercase tracking-wider transition-colors border-b-2 ${
        active
          ? 'bg-terminal-amber text-black font-bold border-terminal-amber -mb-px'
          : 'text-white/60 hover:text-terminal-amber hover:bg-zinc-900 border-transparent'
      }`}
    >
      {label}
    </button>
  );
}

// Usage inside widget:
const [tab, setTab] = useState<Tab>('global');
<div className="flex border-b border-terminal-gray/50 shrink-0">
  <TabButton active={tab === 'global'} onClick={() => setTab('global')} label="Global" />
  <TabButton active={tab === 'company'} onClick={() => setTab('company')} label="Company" />
</div>
```

---

## Scrollable List (non-table)
```tsx
<div className="flex-1 overflow-y-auto">
  {items.map((item) => (
    <div
      key={item.id}
      className="block border-b border-terminal-gray/40 hover:bg-zinc-900 py-2 px-2 cursor-pointer"
    >
      <div className="flex items-start gap-2">
        <span className="text-[10px] text-white/50 shrink-0 font-mono w-20">{item.date}</span>
        <span className="text-xs text-terminal-amber leading-tight">{item.title}</span>
      </div>
    </div>
  ))}
</div>
```

---

## Refresh Button
```tsx
import { useQueryClient } from '@tanstack/react-query';

const queryClient = useQueryClient();

<button
  onClick={() => queryClient.invalidateQueries({ queryKey: ['my-endpoint', symbol] })}
  className="text-[10px] font-mono text-terminal-amber/60 hover:text-terminal-amber px-2 py-0.5 border border-terminal-gray/50 hover:border-terminal-amber transition-colors"
>
  REFRESH
</button>
```

---

## Two-Column Stats Grid
```tsx
<div className="grid grid-cols-2 gap-x-4 gap-y-1 p-2 font-mono text-[10px]">
  {[
    ['Market Cap', value1],
    ['P/E Ratio', value2],
    ['52W High', value3],
    ['52W Low', value4],
  ].map(([label, val]) => (
    <div key={label} className="flex justify-between border-b border-terminal-gray/20 py-0.5">
      <span className="text-white/50">{label}</span>
      <span className="text-terminal-amber">{val ?? '—'}</span>
    </div>
  ))}
</div>
```
