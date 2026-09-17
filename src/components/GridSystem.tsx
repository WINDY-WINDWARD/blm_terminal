'use client';

import React, { useMemo, useRef, useCallback } from 'react';
import Split from 'react-split';
import { useAtom, useAtomValue } from 'jotai';
import { Panel } from './Panel';
import {
  activePanelsAtom,
  createDefaultPanelSizes,
  PANEL_LAYOUTS,
  panelCountAtom,
  panelSizesAtom,
  mergedGroupsAtom,
} from '@/store/terminalStore';

const MIN_PANEL_WIDTH_PX = 220;
const MIN_PANEL_HEIGHT_PX = 180;
const GUTTER_SIZE_PX = 6;

function averageColumnSizes(colSizes: number[][], columnCount: number): number[] {
  if (colSizes.length === 0) {
    return Array.from({ length: columnCount }, () => 100 / columnCount);
  }

  return Array.from({ length: columnCount }, (_, columnIndex) => {
    const total = colSizes.reduce((sum, row) => sum + (row[columnIndex] ?? 0), 0);
    return total / colSizes.length;
  });
}

function resizeAdjacentTracks(
  sizes: number[],
  index: number,
  deltaPercent: number,
  minBeforePercent: number,
  minAfterPercent: number,
): number[] {
  const next = [...sizes];
  const total = sizes[index] + sizes[index + 1];
  const minDelta = minBeforePercent - sizes[index];
  const maxDelta = sizes[index + 1] - minAfterPercent;
  const clampedDelta = Math.min(Math.max(deltaPercent, minDelta), maxDelta);

  next[index] = sizes[index] + clampedDelta;
  next[index + 1] = total - next[index];

  return next;
}

export function GridSystem() {
  const panels = useAtomValue(activePanelsAtom);
  const panelCount = useAtomValue(panelCountAtom);
  const [panelSizes, setPanelSizes] = useAtom(panelSizesAtom);
  const mergedGroups = useAtomValue(mergedGroupsAtom);
  const containerRef = useRef<HTMLDivElement>(null);

  const layout = PANEL_LAYOUTS[panelCount];
  const hasMerges = Object.keys(mergedGroups).length > 0;

  const layoutRows = useMemo(() => {
    return Array.from({ length: layout.rows }, (_, rowIndex) =>
      Array.from({ length: layout.cols }, (_, colIndex) => {
        const panelIndex = rowIndex * layout.cols + colIndex + 1;
        return `panel-${panelIndex}`;
      }),
    );
  }, [layout.cols, layout.rows]);

  const defaultSizes = createDefaultPanelSizes(panelCount);
  const currentSizes =
    panelSizes &&
    panelSizes.rowSizes.length === layout.rows &&
    panelSizes.colSizes.length === layout.rows &&
    panelSizes.colSizes.every((sizes) => sizes.length === layout.cols)
      ? panelSizes
      : defaultSizes;
  const hasMultipleRows = layout.rows > 1;
  const gridColSizes = useMemo(() => {
    const source = currentSizes.mergedColSizes;
    if (source && source.length === layout.cols) {
      return source;
    }
    return averageColumnSizes(currentSizes.colSizes, layout.cols);
  }, [currentSizes.colSizes, currentSizes.mergedColSizes, layout.cols]);

  // ── CSS Grid helpers (used when merges are active) ─────────────────────────

  const gridTemplateAreas = useMemo(() => {
    const grid = Array.from({ length: layout.rows }, (_, r) =>
      Array.from({ length: layout.cols }, (_, c) => {
        const panelId = `panel-${r * layout.cols + c + 1}`;
        for (const [primary, group] of Object.entries(mergedGroups)) {
          if (group.panels.includes(panelId)) {
            return primary;
          }
        }
        return panelId;
      }),
    );
    return grid.map((row) => `"${row.join(' ')}"`).join(' ');
  }, [layout.rows, layout.cols, mergedGroups]);

  const visiblePanels = useMemo(() => {
    const result: string[] = [];
    for (let i = 1; i <= panelCount; i++) {
      const panelId = `panel-${i}`;
      let isVisible = true;
      for (const group of Object.values(mergedGroups)) {
        if (group.panels.includes(panelId)) {
          isVisible = panelId === group.primary;
          break;
        }
      }
      if (isVisible) result.push(panelId);
    }
    return result;
  }, [panelCount, mergedGroups]);

  const handleRowResize = useCallback(
    (e: React.MouseEvent, rowIndex: number) => {
      e.preventDefault();
      const startY = e.clientY;
      const startSizes = [...currentSizes.rowSizes];
      const container = containerRef.current;
      if (!container) return;
      const totalHeight = container.clientHeight;
      const minRowPercent = (MIN_PANEL_HEIGHT_PX / totalHeight) * 100;

      function onMouseMove(moveEvent: MouseEvent) {
        const deltaY = moveEvent.clientY - startY;
        const deltaPercent = (deltaY / totalHeight) * 100;
        const newSizes = resizeAdjacentTracks(
          startSizes,
          rowIndex,
          deltaPercent,
          minRowPercent,
          minRowPercent,
        );
        setPanelSizes({
          ...currentSizes,
          rowSizes: newSizes,
        });
      }

      function onMouseUp() {
        window.removeEventListener('mousemove', onMouseMove);
        window.removeEventListener('mouseup', onMouseUp);
      }

      window.addEventListener('mousemove', onMouseMove);
      window.addEventListener('mouseup', onMouseUp);
    },
    [currentSizes, setPanelSizes],
  );

  const handleColResize = useCallback(
    (e: React.MouseEvent, colIndex: number) => {
      e.preventDefault();
      const startX = e.clientX;
      const startSizes = [...gridColSizes];
      const container = containerRef.current;
      if (!container) return;
      const totalWidth = container.clientWidth;
      const minColPercent = (MIN_PANEL_WIDTH_PX / totalWidth) * 100;

      function onMouseMove(moveEvent: MouseEvent) {
        const deltaX = moveEvent.clientX - startX;
        const deltaPercent = (deltaX / totalWidth) * 100;
        const normalized = resizeAdjacentTracks(
          startSizes,
          colIndex,
          deltaPercent,
          minColPercent,
          minColPercent,
        );
        setPanelSizes({
          ...currentSizes,
          mergedColSizes: normalized,
        });
      }

      function onMouseUp() {
        window.removeEventListener('mousemove', onMouseMove);
        window.removeEventListener('mouseup', onMouseUp);
      }

      window.addEventListener('mousemove', onMouseMove);
      window.addEventListener('mouseup', onMouseUp);
    },
    [gridColSizes, currentSizes, setPanelSizes],
  );

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div
      ref={containerRef}
      data-tour="terminal-grid"
      className="flex-1 min-h-0 overflow-hidden bg-terminal-gray p-[1px] relative"
    >
      {hasMerges ? (
        <>
          <div
            className="grid h-full w-full"
            style={{
              gridTemplateRows: currentSizes.rowSizes
                .map((s) => `${s}%`)
                .join(' '),
              gridTemplateColumns: gridColSizes
                .map((s) => `${s}%`)
                .join(' '),
              gridTemplateAreas: gridTemplateAreas,
            }}
          >
            {visiblePanels.map((panelId) => (
              <div
                key={panelId}
                className="h-full w-full"
                style={{ gridArea: panelId, overflow: 'hidden' }}
              >
                <Panel
                  id={panelId}
                  title={panels[panelId] ?? 'EMPTY'}
                />
              </div>
            ))}
          </div>

          {/* Horizontal resize gutters between rows */}
          {currentSizes.rowSizes.slice(0, -1).map((_, i) => {
            const top = currentSizes.rowSizes
              .slice(0, i + 1)
              .reduce((a, b) => a + b, 0);
            return (
              <div
                key={`row-gutter-${i}`}
                className="absolute cursor-ns-resize hover:bg-terminal-amber/40 z-20"
                style={{
                  top: `calc(${top}% - ${GUTTER_SIZE_PX / 2}px)`,
                  left: 0,
                  right: 0,
                  height: GUTTER_SIZE_PX,
                }}
                onMouseDown={(e) => handleRowResize(e, i)}
              />
            );
          })}

          {/* Vertical resize gutters between columns */}
          {gridColSizes.slice(0, -1).map((_, j) => {
            const left = gridColSizes
              .slice(0, j + 1)
              .reduce((a, b) => a + b, 0);
            return (
              <div
                key={`col-gutter-${j}`}
                className="absolute cursor-ew-resize hover:bg-terminal-amber/40 z-20"
                style={{
                  left: `calc(${left}% - ${GUTTER_SIZE_PX / 2}px)`,
                  top: 0,
                  bottom: 0,
                  width: GUTTER_SIZE_PX,
                }}
                onMouseDown={(e) => handleColResize(e, j)}
              />
            );
          })}
        </>
      ) : hasMultipleRows ? (
        <Split
          key={`layout-${panelCount}-rows-${layout.rows}-cols-${layout.cols}`}
          className="flex h-full min-h-0 flex-col"
          direction="vertical"
          sizes={currentSizes.rowSizes}
          minSize={MIN_PANEL_HEIGHT_PX}
          gutterSize={GUTTER_SIZE_PX}
          onDragEnd={(sizes) => {
            setPanelSizes({
              rowSizes: sizes,
              colSizes: currentSizes.colSizes,
              mergedColSizes: currentSizes.mergedColSizes,
            });
          }}
        >
          {layoutRows.map((row, rowIndex) => (
            <Split
              key={`layout-${panelCount}-row-${rowIndex}-cols-${layout.cols}`}
              className="flex min-h-0"
              direction="horizontal"
              sizes={currentSizes.colSizes[rowIndex]}
              minSize={MIN_PANEL_WIDTH_PX}
              gutterSize={GUTTER_SIZE_PX}
              onDragEnd={(sizes) => {
                setPanelSizes({
                  rowSizes: currentSizes.rowSizes,
                  colSizes: currentSizes.colSizes.map((colSizes, idx) =>
                    idx === rowIndex ? sizes : colSizes,
                  ),
                  mergedColSizes: currentSizes.mergedColSizes,
                });
              }}
            >
              {row.map((panelId) => (
                <Panel key={panelId} id={panelId} title={panels[panelId] ?? 'EMPTY'} />
              ))}
            </Split>
          ))}
        </Split>
      ) : (
        <Split
          key={`layout-${panelCount}-single-${layout.cols}`}
          className="flex h-full min-h-0"
          direction="horizontal"
          sizes={currentSizes.colSizes[0]}
          minSize={MIN_PANEL_WIDTH_PX}
          gutterSize={GUTTER_SIZE_PX}
          onDragEnd={(sizes) => {
            setPanelSizes({
              rowSizes: currentSizes.rowSizes,
              colSizes: [sizes],
              mergedColSizes: currentSizes.mergedColSizes,
            });
          }}
        >
          {layoutRows[0].map((panelId) => (
            <Panel key={panelId} id={panelId} title={panels[panelId] ?? 'EMPTY'} />
          ))}
        </Split>
      )}
    </div>
  );
}
