import React, { ReactNode } from 'react';

interface SplitProps {
  className?: string;
  direction?: 'horizontal' | 'vertical';
  sizes?: number[];
  minSize?: number;
  gutterSize?: number;
  onDragEnd?: (sizes: number[]) => void;
  children: ReactNode;
}

export default function Split({
  className,
  direction,
  sizes,
  onDragEnd,
  children,
}: SplitProps) {
  const handleDragEnd = () => {
    if (onDragEnd) {
      onDragEnd(sizes || [50, 50]);
    }
  };

  return (
    <div className={className} style={{ display: 'flex', flexDirection: direction === 'vertical' ? 'column' : 'row' }} data-testid="react-split">
      {React.Children.map(children, (child, index) => (
        <div key={index} style={{ flex: 1 }} data-testid={`split-child-${index}`}>
          {child}
        </div>
      ))}
    </div>
  );
}