'use client';

import React, { useMemo } from 'react';
import Split from 'react-split';
import { useAtom, useAtomValue } from 'jotai';
import { Panel } from './Panel';
import {
  activePanelsAtom,
  createDefaultPanelSizes,
  PANEL_LAYOUTS,
  panelCountAtom,
  panelSizesAtom,
  type PanelCount,
} from '@/store/terminalStore';

const MIN_PANEL_WIDTH_PX = 220;
const MIN_PANEL_HEIGHT_PX = 180;
const GUTTER_SIZE_PX = 6;

export function GridSystem() {
  const panels = useAtomValue(activePanelsAtom);
  const panelCount = useAtomValue(panelCountAtom);
  const [panelSizes, setPanelSizes] = useAtom(panelSizesAtom);

  const layout = PANEL_LAYOUTS[panelCount];

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

  return (
    <div className="flex-1 min-h-0 overflow-hidden bg-terminal-gray p-[1px]">
      {hasMultipleRows ? (
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
