'use client';

import { useEffect, useState, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';

// ─── Types ────────────────────────────────────────────────────────────────────

interface XmlNode {
  tag: string;
  localName: string;
  text: string | null;
  attrs: Record<string, string>;
  children: XmlNode[];
}

interface XbrlField {
  label: string;
  value: string;
  unit?: string;
  isLong?: boolean;
}

interface XbrlSection {
  title: string;
  fields: XbrlField[];
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function camelToLabel(name: string): string {
  // Split on capital letters, preserve abbreviations
  return name
    .replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2')
    .replace(/([a-z\d])([A-Z])/g, '$1 $2')
    .replace(/^./, (c) => c.toUpperCase())
    .trim();
}

function formatValue(raw: string, unit?: string): string {
  const trimmed = raw.trim();
  if (!trimmed) return '—';

  // Boolean-like
  if (trimmed.toLowerCase() === 'true') return 'Yes';
  if (trimmed.toLowerCase() === 'false') return 'No';

  // Date format: YYYY-MM-DD → DD MMM YYYY
  const dateMatch = trimmed.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (dateMatch) {
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    const month = months[parseInt(dateMatch[2], 10) - 1];
    return `${parseInt(dateMatch[3], 10)} ${month} ${dateMatch[1]}`;
  }

  // Currency amount
  if (unit === 'INR') {
    const num = parseFloat(trimmed);
    if (!isNaN(num)) {
      if (Math.abs(num) >= 1e7) return `₹${(num / 1e7).toFixed(2)} Cr`;
      if (Math.abs(num) >= 1e5) return `₹${(num / 1e5).toFixed(2)} L`;
      return `₹${num.toLocaleString('en-IN')}`;
    }
  }

  // Percentage
  if (unit === 'pure') {
    const num = parseFloat(trimmed);
    if (!isNaN(num)) return `${num}%`;
  }

  return trimmed;
}

function domToXmlNode(el: Element): XmlNode {
  const attrs: Record<string, string> = {};
  for (const attr of Array.from(el.attributes)) {
    attrs[attr.name] = attr.value;
  }
  const children = Array.from(el.children).map(domToXmlNode);
  const text =
    children.length === 0 ? (el.textContent?.trim() ?? null) : null;

  return {
    tag: el.tagName,
    localName: el.localName,
    text,
    attrs,
    children,
  };
}

// ─── XBRL Parser ─────────────────────────────────────────────────────────────

// Fields to extract and their section grouping
const XBRL_SECTIONS: { title: string; keys: string[] }[] = [
  {
    title: 'Company Identity',
    keys: ['NameOfTheCompany', 'NSESymbol', 'BSEScripCode', 'ScripCode', 'ISIN', 'MSEISymbol'],
  },
  {
    title: 'Filing Details',
    keys: [
      'TypeOfAnnouncementPertainingToRegulation30Restructuring',
      'TypeOfEventOfAnnouncementPertainingToRegulation30Restructuring',
      'WhetherEventOrInformationDisclosedIsAnOutcomeOfBoardMeeting',
      'DateOfOccurrenceOfEvent',
      'TimeOfOccurrenceOfEvent',
      'DateOfReport',
    ],
  },
  {
    title: 'Transaction Details',
    keys: [
      'NameOfAcquirer',
      'RelationshipOfAcquirerWithTheListedEntity',
      'IndustryToWhichTheEntityBeingAcquiredBelongs',
      'NatureOfConsiderationForAcquisitionEvent',
      'AmountOfCashConsiderationForAcquisitionEvent',
      'CostOfAcquisitionOrThePriceAtWhichTheSharesAreAcquired',
      'ExistingPercentageOfShareholdingHeldByAcquirer',
      'WhetherTheAcquisitionTransactionWillBeInTranches',
      'WhetherTheAcquisitionWouldFallWithinRelatedPartyTransactions',
    ],
  },
  {
    title: 'Target Entity',
    keys: [
      'TurnoverOfTargetEntity',
      'ProfitAfterTaxOfTargetEntity',
      'NetWorthOfTargetEntity',
      'DateOfIncorporationForAcquisitionEvent',
      'CountryInWhichTheAcquiredEntityHasPresence',
    ],
  },
  {
    title: 'Governance & Approvals',
    keys: [
      'WhetherAcquisitionEventIsDoneAtArmsLength',
      'WhetherAnyGovernmentalOrRegulatoryApprovalsRequiredForTheAcquisition',
      'WhetherThePromoterOrPromoterGroupOrGroupCompaniesIncludingAssociateOrHoldingOrSubsidiaryOrDirectorOrKMPOrSMPAndItsRelativesHaveAnyInterestInTheEntityBeingAcquired',
    ],
  },
];

const XBRL_LONG_FIELDS = new Set([
  'NatureOfInterestAndDetailsThereofForAcquisitionEvent',
  'ObjectsAndImpactOfAcquisitionIncludingButNotLimitedToDisclosureOfReasonsForAcquisitionOfTargetEntityIfItsBusinessIsOutsideTheMainLineOfBusinessOfTheListedEntity',
  'IndicativeTimePeriodForCompletionOfTheAcquisition',
  'ProvideBriefDetailsOfAnyGovernmentalOrRegulatoryApprovalsForTheAcquisition',
  'DetailsOfConsiderationForAcquisitionEvent',
  'BriefBackgroundAboutTheEntityAcquiredInTermsOfProductsLineOfBusinessAcquired',
]);

function parseXbrl(doc: Document): XbrlSection[] | null {
  // Check if this looks like an XBRL document
  const root = doc.documentElement;
  if (!root.tagName.toLowerCase().includes('xbrl')) return null;

  // Collect all leaf elements with their localName as a map
  const fieldMap = new Map<string, { value: string; unit?: string }>();

  const allEls = Array.from(root.querySelectorAll('*'));
  for (const el of allEls) {
    if (el.children.length > 0) continue; // skip non-leaf
    const localName = el.localName;
    const text = el.textContent?.trim() ?? '';
    const unitRef = el.getAttribute('unitRef') ?? undefined;
    if (!fieldMap.has(localName)) {
      fieldMap.set(localName, { value: text, unit: unitRef });
    }
  }

  if (fieldMap.size === 0) return null;

  // Build sections from known keys
  const assignedKeys = new Set<string>();
  const sections: XbrlSection[] = [];

  for (const sectionDef of XBRL_SECTIONS) {
    const fields: XbrlField[] = [];
    for (const key of sectionDef.keys) {
      const entry = fieldMap.get(key);
      if (entry && entry.value !== '') {
        assignedKeys.add(key);
        fields.push({
          label: camelToLabel(key),
          value: formatValue(entry.value, entry.unit),
          unit: entry.unit,
        });
      }
    }
    if (fields.length > 0) {
      sections.push({ title: sectionDef.title, fields });
    }
  }

  // Collect remaining known long text fields
  const longFields: XbrlField[] = [];
  for (const key of XBRL_LONG_FIELDS) {
    const entry = fieldMap.get(key);
    if (entry && entry.value !== '' && !assignedKeys.has(key)) {
      assignedKeys.add(key);
      longFields.push({
        label: camelToLabel(key),
        value: entry.value.trim(),
        isLong: true,
      });
    }
  }

  // Remaining unknown fields
  const otherFields: XbrlField[] = [];
  for (const [key, entry] of fieldMap.entries()) {
    if (!assignedKeys.has(key) && entry.value !== '') {
      otherFields.push({
        label: camelToLabel(key),
        value: formatValue(entry.value, entry.unit),
        unit: entry.unit,
        isLong: entry.value.length > 80,
      });
    }
  }

  if (longFields.length > 0) {
    sections.push({ title: 'Details & Narrative', fields: longFields });
  }
  if (otherFields.length > 0) {
    sections.push({ title: 'Additional Fields', fields: otherFields });
  }

  return sections.length > 0 ? sections : null;
}

// ─── Pretty Print ─────────────────────────────────────────────────────────────

function prettyPrintXml(xml: string): string {
  // Strip existing whitespace between tags
  const stripped = xml.replace(/>\s+</g, '><').trim();
  let indent = 0;
  const lines: string[] = [];

  // Split on tag boundaries while keeping the tags
  const parts = stripped.split(/(?<=>)(?=<)/);

  for (const part of parts) {
    const trimmed = part.trim();
    if (!trimmed) continue;

    const isClosing = /^<\//.test(trimmed);
    const isSelfClosing = /\/>$/.test(trimmed) || /^<\?/.test(trimmed) || /^<!--/.test(trimmed);
    const isOpening = /^<[^/!?]/.test(trimmed) && !isSelfClosing;

    if (isClosing) indent = Math.max(0, indent - 1);
    lines.push('  '.repeat(indent) + trimmed);
    if (isOpening) indent++;
  }

  return lines.join('\n');
}

// ─── Syntax-highlighted raw XML ───────────────────────────────────────────────

function HighlightedXml({ raw }: { raw: string }) {
  const pretty = prettyPrintXml(raw);

  // Split into tokens for coloring: tags, attributes, values, text
  const parts = pretty.split(/(<[^>]*>)/);

  return (
    <pre className="text-[11px] leading-5 font-mono whitespace-pre overflow-x-auto">
      {parts.map((part, i) => {
        if (part.startsWith('<?') || part.startsWith('<!--')) {
          return <span key={i} className="text-white/30">{part}</span>;
        }
        if (part.startsWith('</')) {
          return <span key={i} className="text-blue-400/80">{part}</span>;
        }
        if (part.startsWith('<')) {
          // Tokenise tag name and attributes
          const tagMatch = part.match(/^(<\/?)([\w:-]+)([\s\S]*?)(\/?>)$/);
          if (tagMatch) {
            const [, open, name, rest, close] = tagMatch;
            
            // Highlight attribute names and values without dangerouslySetInnerHTML
            const renderAttributes = (attrStr: string) => {
              const regex = /([\w:-]+)(=)("([^"]*)")/g;
              const parts = [];
              let lastIndex = 0;
              let match;

              while ((match = regex.exec(attrStr)) !== null) {
                if (match.index > lastIndex) {
                  parts.push(<span key={`text-${lastIndex}`}>{attrStr.slice(lastIndex, match.index)}</span>);
                }
                const [, attrName, eq, fullVal] = match;
                parts.push(
                  <span key={`attr-${match.index}`}>
                    <span className="text-yellow-400/80">{attrName}</span>
                    {eq}
                    <span className="text-green-400/70">{fullVal}</span>
                  </span>
                );
                lastIndex = regex.lastIndex;
              }
              if (lastIndex < attrStr.length) {
                parts.push(<span key={`text-${lastIndex}`}>{attrStr.slice(lastIndex)}</span>);
              }
              return parts;
            };

            return (
              <span key={i}>
                <span className="text-blue-400">{open}</span>
                <span className="text-cyan-400">{name}</span>
                <span>{renderAttributes(rest)}</span>
                <span className="text-blue-400">{close}</span>
              </span>
            );
          }
          return <span key={i} className="text-blue-400">{part}</span>;
        }
        // Text content
        return part ? <span key={i} className="text-white/75">{part}</span> : null;
      })}
    </pre>
  );
}

// ─── Generic XML Tree ─────────────────────────────────────────────────────────

function XmlTreeNode({ node, depth = 0 }: { node: XmlNode; depth?: number }) {
  const [collapsed, setCollapsed] = useState(depth > 2);
  const hasChildren = node.children.length > 0;
  const indent = depth * 16;

  const attrStr = Object.entries(node.attrs)
    .filter(([k]) => !k.startsWith('xmlns'))
    .map(([k, v]) => `${k}="${v}"`)
    .join(' ');

  return (
    <div style={{ marginLeft: indent }} className="text-[11px] font-mono leading-5">
      <div className="flex items-start gap-1">
        {hasChildren ? (
          <button
            onClick={() => setCollapsed((c) => !c)}
            className="text-white/30 hover:text-terminal-amber w-3 shrink-0 text-center leading-5"
          >
            {collapsed ? '▶' : '▼'}
          </button>
        ) : (
          <span className="w-3 shrink-0" />
        )}
        <span>
          <span className="text-blue-400">&lt;{node.localName}</span>
          {attrStr && <span className="text-yellow-500/70"> {attrStr}</span>}
          <span className="text-blue-400">&gt;</span>
          {!hasChildren && node.text && (
            <span className="text-white/80"> {node.text}</span>
          )}
          {!hasChildren && (
            <span className="text-blue-400">&lt;/{node.localName}&gt;</span>
          )}
        </span>
      </div>
      {hasChildren && !collapsed && (
        <>
          {node.children.map((child, i) => (
            <XmlTreeNode key={i} node={child} depth={depth + 1} />
          ))}
          <div style={{ marginLeft: 12 }} className="text-blue-400 font-mono text-[11px]">
            &lt;/{node.localName}&gt;
          </div>
        </>
      )}
    </div>
  );
}

// ─── XBRL Viewer ─────────────────────────────────────────────────────────────

function XbrlViewer({ sections }: { sections: XbrlSection[] }) {
  return (
    <div className="space-y-4">
      {sections.map((section) => (
        <div key={section.title} className="border border-terminal-gray/30 rounded">
          <div className="px-3 py-1.5 bg-zinc-900 border-b border-terminal-gray/30">
            <span className="text-terminal-amber text-[11px] font-mono font-semibold uppercase tracking-wider">
              {section.title}
            </span>
          </div>
          <div className="divide-y divide-terminal-gray/20">
            {section.fields.map((field) =>
              field.isLong ? (
                <div key={field.label} className="px-3 py-2">
                  <div className="text-[10px] text-white/40 font-mono mb-1 uppercase tracking-wide">
                    {field.label}
                  </div>
                  <div className="text-xs text-white/80 font-mono whitespace-pre-wrap leading-5">
                    {field.value}
                  </div>
                </div>
              ) : (
                <div key={field.label} className="flex items-start gap-3 px-3 py-1.5">
                  <span className="text-[10px] text-white/40 font-mono w-56 shrink-0 pt-0.5 leading-4">
                    {field.label}
                  </span>
                  <span className="text-xs text-white/90 font-mono flex-1">{field.value}</span>
                </div>
              )
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

type ViewerState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'xbrl'; sections: XbrlSection[]; raw: string; companyName?: string; eventType?: string }
  | { status: 'tree'; root: XmlNode; raw: string };

function FilingViewer() {
  const params = useSearchParams();
  const url = params.get('url') ?? '';
  const [state, setState] = useState<ViewerState>({ status: 'loading' });
  const [showRaw, setShowRaw] = useState(false);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (!url) {
      setState({ status: 'error', message: 'No URL provided.' });
      return;
    }

    setState({ status: 'loading' });

    const proxyUrl = `/api/filing-xml?url=${encodeURIComponent(url)}`;
    fetch(proxyUrl)
      .then(async (res) => {
        if (!res.ok) {
          const json = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
          throw new Error(json.error ?? `HTTP ${res.status}`);
        }
        return res.text();
      })
      .then((text) => {
        const parser = new DOMParser();
        const doc = parser.parseFromString(text, 'application/xml');

        const parseErr = doc.querySelector('parsererror');
        if (parseErr) throw new Error('Failed to parse XML document');

        // Try XBRL structured view
        const sections = parseXbrl(doc);
        if (sections) {
          const companyEl = doc.querySelector('NameOfTheCompany');
          const eventEl = doc.querySelector(
            'TypeOfEventOfAnnouncementPertainingToRegulation30Restructuring'
          );
          setState({
            status: 'xbrl',
            sections,
            raw: text,
            companyName: companyEl?.textContent?.trim(),
            eventType: eventEl?.textContent?.trim(),
          });
        } else {
          // Fall back to generic tree
          const root = domToXmlNode(doc.documentElement);
          setState({ status: 'tree', root, raw: text });
        }
      })
      .catch((err: unknown) => {
        const message = err instanceof Error ? err.message : 'Unknown error';
        setState({ status: 'error', message });
      });
  }, [url]);

  const filenameFromUrl = url ? url.split('/').pop() ?? url : '';

  return (
    <div className="min-h-screen bg-terminal-bg text-white font-mono overflow-y-auto" style={{ height: '100vh', overflowY: 'auto' }}>
      {/* Header */}
      <div className="sticky top-0 z-10 bg-zinc-950 border-b border-terminal-gray/30 px-4 py-2 flex items-center gap-3">
        <span className="text-terminal-amber font-semibold text-sm">NSE FILING VIEWER</span>
        <span className="text-white/30 text-xs hidden sm:block truncate max-w-xs" title={url}>
          {filenameFromUrl}
        </span>
        <div className="ml-auto flex items-center gap-3">
          {(state.status === 'xbrl' || state.status === 'tree') && (
            <button
              onClick={() => setShowRaw((v) => !v)}
              className={`text-[10px] px-2 py-0.5 border rounded transition-colors font-mono ${
                showRaw
                  ? 'border-terminal-amber text-terminal-amber'
                  : 'border-terminal-gray/40 text-white/40 hover:text-white/70'
              }`}
            >
              {showRaw ? 'STRUCTURED' : 'RAW XML'}
            </button>
          )}
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[10px] px-2 py-0.5 border border-terminal-gray/40 text-white/40 hover:text-white/70 rounded transition-colors"
          >
            OPEN ORIGINAL ↗
          </a>
        </div>
      </div>

      {/* Content */}
      <div className="max-w-4xl mx-auto px-4 py-6">
        {state.status === 'loading' && (
          <div className="flex flex-col items-center justify-center h-64 gap-3">
            <div className="w-5 h-5 border-2 border-terminal-amber border-t-transparent rounded-full animate-spin" />
            <span className="text-white/40 text-xs">Fetching filing...</span>
          </div>
        )}

        {state.status === 'error' && (
          <div className="mt-12 text-center">
            <div className="text-terminal-red text-sm mb-2">Failed to load filing</div>
            <div className="text-white/40 text-xs">{state.message}</div>
            <a
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-4 inline-block text-terminal-amber text-xs hover:underline"
            >
              Try opening directly ↗
            </a>
          </div>
        )}

        {state.status === 'xbrl' && !showRaw && (
          <>
            {/* Filing header card */}
            <div className="mb-5 border border-terminal-amber/30 rounded bg-terminal-amber/5 px-4 py-3">
              <div className="text-xs text-white/40 mb-0.5">REGULATION 30 FILING</div>
              {state.companyName && (
                <div className="text-base font-semibold text-white">{state.companyName}</div>
              )}
              {state.eventType && (
                <div className="text-xs text-terminal-amber mt-0.5">{state.eventType}</div>
              )}
            </div>
            <XbrlViewer sections={state.sections} />
          </>
        )}

        {state.status === 'tree' && !showRaw && (
          <>
            <div className="mb-4 text-xs text-white/40">
              Generic XML — no XBRL schema detected
            </div>
            <div className="border border-terminal-gray/30 rounded p-3 overflow-x-auto">
              <XmlTreeNode node={state.root} depth={0} />
            </div>
          </>
        )}

        {(state.status === 'xbrl' || state.status === 'tree') && showRaw && (
          <div className="border border-terminal-gray/30 rounded p-3 overflow-x-auto bg-zinc-950">
            <HighlightedXml raw={state.raw} />
          </div>
        )}
      </div>
    </div>
  );
}

export default function FilingPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-terminal-bg flex items-center justify-center">
          <div className="w-5 h-5 border-2 border-terminal-amber border-t-transparent rounded-full animate-spin" />
        </div>
      }
    >
      <FilingViewer />
    </Suspense>
  );
}
